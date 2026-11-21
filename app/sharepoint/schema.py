"""How each portal table becomes a SharePoint list.

One list per table, named `<prefix><Table>` (tblApplications ->
RTPS_Applications). Every SQLite column becomes a typed SharePoint column in
PascalCase (application_number -> ApplicationNumber), plus:

- `RecordId` — the row's id in the portal, indexed. Foreign keys between
  lists are plain numbers that point at a RecordId.
- `Title` — SharePoint's built-in column, filled with a readable label so a
  list is legible in the browser.

Columns that must never leave the portal (password hashes, file bytes) are
not mapped. Dates are stored as SharePoint dateTime columns in UTC.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

# Columns that never go to SharePoint.
EXCLUDED = {
    "tblUsers": {"password_hash", "salt"},   # sign-in is Microsoft 365 in SharePoint mode
    "tblDocuments": {"content"},             # the bytes live in the Documents library
}

# Filled locally when a row arrives from SharePoint without them.
LOCAL_DEFAULTS = {
    ("tblUsers", "password_hash"): "!",      # matches no password: unusable by design
    ("tblUsers", "salt"): "!",
}

DATE_ONLY = {"submission_date"}
DATETIME = {
    "created_at", "updated_at", "submitted_at", "approved_at", "last_login",
    "verified_at", "raised_at", "responded_at", "closed_at", "action_at",
    "approval_date", "lock_date", "unlock_requested_at", "unlock_date",
    "relock_date", "upload_time", "sent_time", "timestamp",
} | DATE_ONLY

# Free text that can run past SharePoint's 255-character single-line limit.
LONG_TEXT = {
    "remarks", "comments", "comment", "message", "old_value", "new_value",
    "reason", "description", "closure_remarks", "unlock_reason",
    "recommendation", "browser", "field_value", "item_text", "setting_value",
    "label", "web_url",
}

# Built-in SharePoint field names a column must not take.
RESERVED = {"ID", "Id", "Title", "Created", "Modified", "Author", "Editor",
            "Version", "ContentType", "Attachments", "Order", "GUID",
            "FileRef", "FileLeafRef", "Type"}

TITLE_COLUMN = {
    "tblRoles": "role_name",
    "tblPermissions": "permission_code",
    "tblDivisionMaster": "division_name",
    "tblDistrictMaster": "district_name",
    "tblBlockMaster": "block_name",
    "tblOfficeMaster": "office_name",
    "tblDepartmentMaster": "department_name",
    "tblServiceMaster": "service_name",
    "tblUsers": "username",
    "tblApplications": "application_number",
    "tblApplicationDetails": "field_name",
    "tblVerificationChecklist": "item_code",
    "tblCorrections": "reason",
    "tblApproval": "current_level",
    "tblApprovalHistory": "level",
    "tblDocuments": "file_name",
    "tblNotifications": "event",
    "tblAuditLogs": "activity",
    "tblSettings": "setting_key",
}


def pascal(name: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in name.split("_"))


@dataclass
class Column:
    name: str            # SQLite column
    sp_name: str         # SharePoint internal name
    kind: str            # integer | real | text | longtext | datetime | date
    notnull: bool = False

    def definition(self) -> dict:
        d: dict = {"name": self.sp_name}
        if self.kind == "integer":
            d["number"] = {"decimalPlaces": "none"}
        elif self.kind == "real":
            d["number"] = {"decimalPlaces": "automatic"}
        elif self.kind == "datetime":
            d["dateTime"] = {"format": "dateTime"}
        elif self.kind == "date":
            d["dateTime"] = {"format": "dateOnly"}
        elif self.kind == "longtext":
            d["text"] = {"allowMultipleLines": True, "linesForEditing": 6}
        else:
            d["text"] = {"maxLength": 255}
        return d

    # --- value conversion ----------------------------------------------

    def to_sp(self, value):
        if value is None:
            return None
        if self.kind in ("datetime", "date"):
            text = str(value).strip()
            if len(text) == 10:                      # YYYY-MM-DD
                return f"{text}T00:00:00Z"
            return text.replace(" ", "T")[:19] + "Z"
        if self.kind == "integer":
            return int(value)
        if self.kind == "real":
            return float(value)
        text = str(value)
        return text[:255] if self.kind == "text" else text

    def from_sp(self, value):
        if value in (None, ""):
            return None
        if self.kind == "date":
            return str(value)[:10]
        if self.kind == "datetime":
            return str(value).replace("T", " ").rstrip("Z")[:19]
        if self.kind == "integer":
            return int(round(float(value)))
        if self.kind == "real":
            return float(value)
        return str(value)


@dataclass
class ListSpec:
    table: str
    list_name: str
    columns: list[Column] = field(default_factory=list)

    def definitions(self) -> list[dict]:
        return [{"name": "RecordId", "number": {"decimalPlaces": "none"},
                 "indexed": True}] + [c.definition() for c in self.columns]

    def title_for(self, row: dict) -> str:
        col = TITLE_COLUMN.get(self.table)
        value = row.get(col) if col else None
        label = str(value) if value not in (None, "") else f"{self.table[3:]} #{row['rowid']}"
        return label[:255]

    def fields_for(self, row: dict, *, include_nulls: bool) -> dict:
        """The SharePoint `fields` payload for one local row."""
        out = {"Title": self.title_for(row), "RecordId": int(row["rowid"])}
        for c in self.columns:
            value = c.to_sp(row.get(c.name))
            if value is None and not include_nulls:
                continue
            out[c.sp_name] = value
        return out

    def row_from(self, fields: dict) -> dict:
        """A local row from a SharePoint item's `fields` (rowid excluded)."""
        return {c.name: c.from_sp(fields.get(c.sp_name)) for c in self.columns}


def _kind(table: str, name: str, decl: str) -> str:
    decl = (decl or "").upper()
    if name in DATE_ONLY:
        return "date"
    if name in DATETIME:
        return "datetime"
    if "INT" in decl:
        return "integer"
    if "REAL" in decl or "FLOA" in decl or "DOUB" in decl:
        return "real"
    return "longtext" if name in LONG_TEXT else "text"


def build(schema_sql: str, prefix: str) -> dict[str, ListSpec]:
    """Every table in the schema, as the list that stores it."""
    mem = sqlite3.connect(":memory:")
    mem.executescript(schema_sql)
    tables = [r[0] for r in mem.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
        " AND name LIKE 'tbl%' ORDER BY name")]
    specs: dict[str, ListSpec] = {}
    for table in tables:
        spec = ListSpec(table, f"{prefix}{table[3:]}")
        used = set()
        for _cid, name, decl, notnull, _default, _pk in mem.execute(
                f"PRAGMA table_info({table})"):
            if name in EXCLUDED.get(table, set()):
                continue
            sp_name = pascal(name)
            if sp_name in RESERVED:
                sp_name = f"Rtps{sp_name}"
            while sp_name in used:
                sp_name += "_"
            used.add(sp_name)
            spec.columns.append(Column(name, sp_name, _kind(table, name, decl),
                                       bool(notnull)))
        specs[table] = spec
    mem.close()
    return specs
