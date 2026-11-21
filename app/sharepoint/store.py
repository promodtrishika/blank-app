"""SharePoint lists as the system of record, with a local read cache.

Every screen keeps reading SQL. Underneath, the SQLite file is a cache of the
SharePoint lists:

- **Writes** — triggers on every table queue each insert, update and delete in
  `_sync_outbox`. `push()` drains the queue to SharePoint through $batch (the
  entry point calls it at the end of every page run). A push that fails stays
  queued and is retried; nothing is lost while SharePoint is unreachable.
- **Reads from elsewhere** — `pull()` follows each list's delta link, so
  edits made directly in SharePoint (or by Power Automate) reach the portal.
  A 410 from Graph, or a list where delta is unavailable, falls back to a full
  re-read of that list.
- **Conflicts** — a row with a change still queued locally is not overwritten
  by a pull; once pushed, the last write wins.

Run one portal instance per SharePoint site: the portal allocates record ids.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Iterable

from app.sharepoint import schema
from app.sharepoint.config import SharePointConfig
from app.sharepoint.files import Libraries
from app.sharepoint.graph import GraphClient, GraphError

SYNC_DDL = """
CREATE TABLE IF NOT EXISTS _sync_state (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    applying      INTEGER NOT NULL DEFAULT 0,
    site_id       TEXT,
    hydrated      INTEGER NOT NULL DEFAULT 0,
    last_pull     REAL,
    last_push     REAL,
    last_error    TEXT,
    last_error_at REAL
);
INSERT OR IGNORE INTO _sync_state(id, applying) VALUES (1, 0);
CREATE TABLE IF NOT EXISTS _sync_outbox (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    tbl        TEXT NOT NULL,
    row_id     INTEGER NOT NULL,
    op         TEXT NOT NULL,
    queued_at  TEXT NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);
CREATE INDEX IF NOT EXISTS ix_outbox_row ON _sync_outbox(tbl, row_id);
CREATE TABLE IF NOT EXISTS _sp_map (
    tbl    TEXT NOT NULL,
    row_id INTEGER NOT NULL,
    sp_id  TEXT NOT NULL,
    PRIMARY KEY (tbl, row_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_sp_map_sp ON _sp_map(tbl, sp_id);
CREATE TABLE IF NOT EXISTS _sp_delta (
    tbl        TEXT PRIMARY KEY,
    delta_link TEXT
);
"""

TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS _sync_{t}_ins AFTER INSERT ON {t}
WHEN (SELECT applying FROM _sync_state WHERE id = 1) = 0
BEGIN
    INSERT INTO _sync_outbox(tbl, row_id, op, queued_at)
    VALUES ('{t}', NEW.rowid, 'upsert', datetime('now'));
END;
CREATE TRIGGER IF NOT EXISTS _sync_{t}_upd AFTER UPDATE ON {t}
WHEN (SELECT applying FROM _sync_state WHERE id = 1) = 0
BEGIN
    INSERT INTO _sync_outbox(tbl, row_id, op, queued_at)
    VALUES ('{t}', NEW.rowid, 'upsert', datetime('now'));
END;
CREATE TRIGGER IF NOT EXISTS _sync_{t}_del AFTER DELETE ON {t}
WHEN (SELECT applying FROM _sync_state WHERE id = 1) = 0
BEGIN
    INSERT INTO _sync_outbox(tbl, row_id, op, queued_at)
    VALUES ('{t}', OLD.rowid, 'delete', datetime('now'));
END;
"""

OK_STATUSES = {200, 201, 204}


class SharePointStore:
    def __init__(self, conn: sqlite3.Connection, client: GraphClient,
                 config: SharePointConfig, schema_sql: str,
                 lock: threading.RLock | None = None):
        self.conn = conn
        self.client = client
        self.config = config
        self.specs = schema.build(schema_sql, config.list_prefix)
        self.files = Libraries(client, config)
        self.lock = lock or threading.RLock()

    # --- setup ----------------------------------------------------------

    def install(self) -> None:
        """Sync bookkeeping and change triggers on every portal table."""
        with self.lock:
            self.conn.executescript(SYNC_DDL)
            for table in self.specs:
                self.conn.executescript(TRIGGERS.format(t=table))
            self.conn.commit()

    def provision(self) -> list[str]:
        """Create any missing list, column or library. Returns what it made."""
        made: list[str] = []
        existing = self.client.lists(refresh=True)
        site = self.client.site_id()
        for spec in self.specs.values():
            if spec.list_name not in existing:
                self.client.create_list(spec.list_name, spec.definitions())
                made.append(f"list {spec.list_name}")
                continue
            have = {c["name"] for c in self.client.all(
                f"sites/{site}/lists/{existing[spec.list_name]}/columns",
                params={"$select": "name"})}
            for definition in spec.definitions():
                if definition["name"] not in have:
                    self.client.request(
                        "POST", f"sites/{site}/lists/{existing[spec.list_name]}/columns",
                        json=definition)
                    made.append(f"column {spec.list_name}.{definition['name']}")
        for library in (self.config.documents_library, self.config.reports_library):
            if library not in existing:
                self.client.create_list(library, [], template="documentLibrary")
                made.append(f"library {library}")
        return made

    # --- helpers --------------------------------------------------------

    @contextmanager
    def applying(self):
        """Changes made inside are SharePoint's own: they are not queued back."""
        # SharePoint has no foreign keys, and items arrive in any order, so the
        # cache does not enforce them while applying. The pragma is a no-op
        # inside a transaction: commit first, or it is silently ignored.
        self.conn.commit()
        self.conn.execute("PRAGMA foreign_keys = OFF")
        self.conn.execute("UPDATE _sync_state SET applying = 1 WHERE id = 1")
        try:
            yield
        finally:
            self.conn.execute("UPDATE _sync_state SET applying = 0 WHERE id = 1")
            self.conn.commit()
            self.conn.execute("PRAGMA foreign_keys = ON")

    def _list_id(self, table: str) -> str:
        name = self.specs[table].list_name
        lists = self.client.lists()
        if name not in lists:
            lists = self.client.lists(refresh=True)
        if name not in lists:
            raise GraphError(404, "listNotFound",
                             f"The SharePoint list {name!r} does not exist. "
                             "Run the provisioning step first.")
        return lists[name]

    def _items_path(self, table: str) -> str:
        return f"sites/{self.client.site_id()}/lists/{self._list_id(table)}/items"

    def _sp_id(self, table: str, row_id: int) -> str | None:
        row = self.conn.execute("SELECT sp_id FROM _sp_map WHERE tbl = ? AND row_id = ?",
                                (table, row_id)).fetchone()
        return row[0] if row else None

    def _row_for_sp(self, table: str, sp_id: str) -> int | None:
        row = self.conn.execute("SELECT row_id FROM _sp_map WHERE tbl = ? AND sp_id = ?",
                                (table, sp_id)).fetchone()
        return row[0] if row else None

    def _map(self, table: str, row_id: int, sp_id: str) -> None:
        self.conn.execute("DELETE FROM _sp_map WHERE tbl = ? AND sp_id = ?", (table, sp_id))
        self.conn.execute("INSERT OR REPLACE INTO _sp_map(tbl, row_id, sp_id)"
                          " VALUES (?,?,?)", (table, row_id, sp_id))

    def _pending(self, table: str, row_id: int) -> bool:
        return self.conn.execute("SELECT 1 FROM _sync_outbox WHERE tbl = ? AND row_id = ?"
                                 " LIMIT 1", (table, row_id)).fetchone() is not None

    def _row(self, table: str, row_id: int) -> dict | None:
        cur = self.conn.execute(f"SELECT rowid AS rowid, * FROM {table} WHERE rowid = ?",
                                (row_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return dict(zip([d[0] for d in cur.description], row))

    def _error(self, message: str) -> None:
        self.conn.execute("UPDATE _sync_state SET last_error = ?, last_error_at = ?"
                          " WHERE id = 1", (message[:500], time.time()))
        self.conn.commit()

    # --- push: local changes to SharePoint ----------------------------

    def pending_count(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM (SELECT DISTINCT tbl, row_id FROM _sync_outbox)"
        ).fetchone()[0]

    def push(self, limit: int = 2000) -> dict:
        """Send queued changes to SharePoint. Returns counts."""
        with self.lock:
            queued = self.conn.execute(
                "SELECT seq, tbl, row_id, op FROM _sync_outbox ORDER BY seq LIMIT ?",
                (limit,)).fetchall()
            if not queued:
                return {"pushed": 0, "failed": 0}
            # Only the last change per row matters.
            last: dict[tuple[str, int], tuple[int, str]] = {}
            for seq, tbl, row_id, op in queued:
                last[(tbl, row_id)] = (seq, op)

            calls, keys = [], []
            try:
                for (tbl, row_id), (seq, op) in last.items():
                    call = self._call_for(tbl, row_id, op)
                    if call is None:          # nothing to tell SharePoint
                        self._done(tbl, row_id, seq)
                        continue
                    calls.append(call)
                    keys.append((tbl, row_id, seq, call))
                self.conn.commit()
                results = self.client.batch(calls) if calls else []
            except GraphError as exc:
                self._fail_all(last, str(exc))
                return {"pushed": 0, "failed": len(last)}

            pushed = failed = 0
            for (tbl, row_id, seq, call), res in zip(keys, results):
                status, body = res["status"], res["body"] or {}
                if status in OK_STATUSES:
                    if call["method"] == "POST":
                        self._map(tbl, row_id, str(body["id"]))
                    elif call["method"] == "DELETE":
                        self.conn.execute("DELETE FROM _sp_map WHERE tbl = ? AND row_id = ?",
                                          (tbl, row_id))
                    self._done(tbl, row_id, seq)
                    pushed += 1
                elif status == 404 and call["method"] == "DELETE":
                    self.conn.execute("DELETE FROM _sp_map WHERE tbl = ? AND row_id = ?",
                                      (tbl, row_id))
                    self._done(tbl, row_id, seq)
                    pushed += 1
                elif status == 404 and call["method"] == "PATCH":
                    # Deleted in SharePoint while changed here: the portal's
                    # change wins, so the item is created again next push.
                    self.conn.execute("DELETE FROM _sp_map WHERE tbl = ? AND row_id = ?",
                                      (tbl, row_id))
                    failed += 1
                else:
                    message = (body.get("error") or {}).get("message", f"HTTP {status}")
                    self.conn.execute(
                        "UPDATE _sync_outbox SET attempts = attempts + 1, last_error = ?"
                        " WHERE tbl = ? AND row_id = ?", (message[:500], tbl, row_id))
                    self._error(f"{self.specs[tbl].list_name}: {message}")
                    failed += 1
            self.conn.execute("UPDATE _sync_state SET last_push = ? WHERE id = 1",
                              (time.time(),))
            if not failed:
                self.conn.execute("UPDATE _sync_state SET last_error = NULL WHERE id = 1")
            self.conn.commit()
            return {"pushed": pushed, "failed": failed}

    def _done(self, tbl: str, row_id: int, seq: int) -> None:
        self.conn.execute("DELETE FROM _sync_outbox WHERE tbl = ? AND row_id = ?"
                          " AND seq <= ?", (tbl, row_id, seq))

    def _fail_all(self, last: dict, message: str) -> None:
        for (tbl, row_id) in last:
            self.conn.execute("UPDATE _sync_outbox SET attempts = attempts + 1,"
                              " last_error = ? WHERE tbl = ? AND row_id = ?",
                              (message[:500], tbl, row_id))
        self._error(message)

    def _call_for(self, tbl: str, row_id: int, op: str) -> dict | None:
        sp_id = self._sp_id(tbl, row_id)
        row = self._row(tbl, row_id) if op == "upsert" else None
        if op == "delete" or row is None:
            if not sp_id:
                return None
            return {"method": "DELETE", "url": f"{self._items_path(tbl)}/{sp_id}"}
        if tbl == "tblDocuments" and row.get("content") is not None:
            row = self._upload_document(row)
        spec = self.specs[tbl]
        if sp_id:
            return {"method": "PATCH", "url": f"{self._items_path(tbl)}/{sp_id}/fields",
                    "body": spec.fields_for(row, include_nulls=True)}
        return {"method": "POST", "url": self._items_path(tbl),
                "body": {"fields": spec.fields_for(row, include_nulls=False)}}

    def _upload_document(self, row: dict) -> dict:
        """Move a document's bytes into the library; keep only the reference."""
        number = self.conn.execute(
            "SELECT application_number FROM tblApplications WHERE application_id = ?",
            (row["application_id"],)).fetchone()
        stored = self.files.upload_document(number[0] if number else "unfiled",
                                            row["file_name"], row["content"])
        with self.applying():
            self.conn.execute(
                "UPDATE tblDocuments SET content = NULL, sp_item_id = ?,"
                " sp_version_id = ?, web_url = ? WHERE rowid = ?",
                (stored["sp_item_id"], stored["sp_version_id"], stored["web_url"],
                 row["rowid"]))
        row.update(stored, content=None)
        return row

    # --- pull: SharePoint changes into the cache -----------------------

    def pull(self, tables: Iterable[str] | None = None) -> dict:
        with self.lock:
            changed = 0
            for table in tables or self.specs:
                link = self.conn.execute("SELECT delta_link FROM _sp_delta WHERE tbl = ?",
                                         (table,)).fetchone()
                try:
                    if link and link[0]:
                        items, new_link = self._delta(link[0])
                        if items is None:          # 410: start the list afresh
                            changed += self.reconcile(table)
                            continue
                        changed += self._apply(table, items)
                        self._save_link(table, new_link)
                    else:
                        changed += self.reconcile(table)
                except GraphError as exc:
                    self._error(f"{self.specs[table].list_name}: {exc}")
            self.conn.execute("UPDATE _sync_state SET last_pull = ? WHERE id = 1",
                              (time.time(),))
            self.conn.commit()
            return {"changed": changed}

    def pull_if_stale(self) -> None:
        last = self.conn.execute("SELECT last_pull FROM _sync_state WHERE id = 1"
                                 ).fetchone()[0]
        if last is None or time.time() - last >= self.config.pull_interval_seconds:
            self.pull()

    def _delta(self, url: str) -> tuple[list[dict] | None, str | None]:
        items: list[dict] = []
        while True:
            resp = self.client.request("GET", url, raw=True, ok=(410,))
            if resp.status_code == 410:
                return None, None
            body = resp.json()
            items.extend(body.get("value", []))
            if body.get("@odata.nextLink"):
                url = body["@odata.nextLink"]
                continue
            return items, body.get("@odata.deltaLink")

    def _save_link(self, table: str, link: str | None) -> None:
        self.conn.execute("INSERT OR REPLACE INTO _sp_delta(tbl, delta_link) VALUES (?,?)",
                          (table, link))

    def reconcile(self, table: str) -> int:
        """Re-read a whole list and make the cache match it."""
        path = f"{self._items_path(table)}/delta"
        try:
            items, link = self._delta(f"{self.client.url(path)}?$expand=fields&$top=500")
            if items is None:
                raise GraphError(410, "resyncRequired", "fresh enumeration refused")
        except GraphError as exc:
            if exc.status not in (400, 404, 410, 501):
                raise
            # Delta unavailable for this list: read it plainly and reconcile
            # in full every pull.
            items = self.client.all(self._items_path(table),
                                    params={"$expand": "fields", "$top": "500"})
            link = None
        changed = self._apply(table, items)
        seen = {str(i["id"]) for i in items if not i.get("deleted")}
        gone = [r for r in self.conn.execute(
            "SELECT row_id, sp_id FROM _sp_map WHERE tbl = ?", (table,)).fetchall()
            if r[1] not in seen]
        with self.applying():
            for row_id, sp_id in gone:
                if self._pending(table, row_id):
                    continue
                self.conn.execute(f"DELETE FROM {table} WHERE rowid = ?", (row_id,))
                self.conn.execute("DELETE FROM _sp_map WHERE tbl = ? AND sp_id = ?",
                                  (table, sp_id))
                changed += 1
        self._save_link(table, link)
        self.conn.commit()
        return changed

    def _apply(self, table: str, items: list[dict]) -> int:
        spec = self.specs[table]
        latest: dict[str, dict] = {}
        for item in items:                       # the last occurrence wins
            latest[str(item["id"])] = item
        writebacks: list[tuple[str, int]] = []
        changed = 0
        with self.applying():
            for sp_id, item in latest.items():
                if item.get("deleted"):
                    row_id = self._row_for_sp(table, sp_id)
                    if row_id is not None and not self._pending(table, row_id):
                        self.conn.execute(f"DELETE FROM {table} WHERE rowid = ?", (row_id,))
                        self.conn.execute("DELETE FROM _sp_map WHERE tbl = ? AND sp_id = ?",
                                          (table, sp_id))
                        changed += 1
                    continue
                fields = item.get("fields") or {}
                if fields.get("ContentType") == "Folder":
                    continue
                row_id = self._row_for_sp(table, sp_id)
                if row_id is None and fields.get("RecordId") not in (None, ""):
                    row_id = int(float(fields["RecordId"]))
                needs_writeback = fields.get("RecordId") in (None, "")
                if row_id is None:
                    row_id = (self.conn.execute(
                        f"SELECT COALESCE(MAX(rowid), 0) + 1 FROM {table}").fetchone()[0])
                if self._pending(table, row_id):
                    continue
                try:
                    self._upsert(table, spec, row_id, spec.row_from(fields))
                except sqlite3.IntegrityError as exc:
                    self._error(f"{spec.list_name} item {sp_id} was not loaded: {exc}")
                    continue
                self._map(table, row_id, sp_id)
                changed += 1
                if needs_writeback:
                    writebacks.append((sp_id, row_id))
        if writebacks:
            # Items made directly in SharePoint learn the id the portal gave them.
            self.client.batch([{"method": "PATCH",
                                "url": f"{self._items_path(table)}/{sp}/fields",
                                "body": {"RecordId": rid}} for sp, rid in writebacks])
        return changed

    def _rowid_alias(self, table: str) -> str | None:
        """The INTEGER PRIMARY KEY column that is the rowid, if the table has one."""
        if not hasattr(self, "_aliases"):
            self._aliases: dict[str, str | None] = {}
        if table not in self._aliases:
            info = list(self.conn.execute(f"PRAGMA table_info({table})"))
            pk = [r for r in info if r[5] >= 1]
            self._aliases[table] = (pk[0][1] if len(pk) == 1
                                    and (pk[0][2] or "").upper() == "INTEGER" else None)
        return self._aliases[table]

    def _upsert(self, table: str, spec: schema.ListSpec, row_id: int,
                values: dict) -> None:
        alias = self._rowid_alias(table)
        if alias and alias in values:
            values[alias] = row_id
        exists = self.conn.execute(f"SELECT 1 FROM {table} WHERE rowid = ?",
                                   (row_id,)).fetchone()
        if exists:
            sets = ", ".join(f"{c} = ?" for c in values)
            self.conn.execute(f"UPDATE {table} SET {sets} WHERE rowid = ?",
                              [*values.values(), row_id])
            return
        for (tbl, col), default in schema.LOCAL_DEFAULTS.items():
            if tbl == table and col not in values:
                values[col] = default
        cols = ", ".join(["rowid", *values])
        marks = ", ".join("?" * (len(values) + 1))
        self.conn.execute(f"INSERT INTO {table}({cols}) VALUES ({marks})",
                          [row_id, *values.values()])

    # --- first load and migration -------------------------------------

    def hydrate(self) -> int:
        """Fill an empty cache from SharePoint."""
        with self.lock:
            site = self.client.site_id()
            total = 0
            for table in self.specs:
                total += self.reconcile(table)
            self.conn.execute("UPDATE _sync_state SET site_id = ?, hydrated = 1,"
                              " last_pull = ? WHERE id = 1", (site, time.time()))
            self.conn.commit()
            return total

    def needs_hydrate(self) -> bool:
        row = self.conn.execute("SELECT site_id, hydrated FROM _sync_state WHERE id = 1"
                                ).fetchone()
        return not row or not row[1] or row[0] != self.client.site_id()

    def reset_cache(self) -> None:
        """Empty every portal table and the sync bookkeeping."""
        with self.lock, self.applying():
            for table in self.specs:
                self.conn.execute(f"DELETE FROM {table}")
            for t in ("_sync_outbox", "_sp_map", "_sp_delta"):
                self.conn.execute(f"DELETE FROM {t}")
            self.conn.execute("UPDATE _sync_state SET hydrated = 0, site_id = NULL"
                              " WHERE id = 1")

    def migrate_from(self, source: sqlite3.Connection, force: bool = False,
                     progress=print, tables: Iterable[str] | None = None) -> int:
        """Copy every row of a portal database into empty SharePoint lists."""
        chosen = [t for t in self.specs if tables is None or t in set(tables)]
        if not force:
            for table in chosen:
                page = self.client.get(f"{self._items_path(table)}",
                                       params={"$top": "1", "$select": "id"})
                if page.get("value"):
                    raise RuntimeError(
                        f"{self.specs[table].list_name} already has items. Migrating "
                        "again would duplicate them; pass force=True to do it anyway.")
        total = 0
        for table in chosen:
            spec = self.specs[table]
            cur = source.execute(f"SELECT rowid AS rowid, * FROM {table}")
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            if table == "tblDocuments":
                rows = [self._migrate_document(source, r) for r in rows]
            calls = [{"method": "POST", "url": self._items_path(table),
                      "body": {"fields": spec.fields_for(r, include_nulls=False)}}
                     for r in rows]
            results = self.client.batch(calls) if calls else []
            bad = [r for r in results if r["status"] not in OK_STATUSES]
            if bad:
                first = (bad[0]["body"] or {}).get("error", {}).get("message", bad[0]["status"])
                raise RuntimeError(f"{spec.list_name}: {len(bad)} item(s) failed — {first}")
            total += len(rows)
            progress(f"  {spec.list_name}: {len(rows)} item(s)")
        return total

    def _migrate_document(self, source: sqlite3.Connection, row: dict) -> dict:
        if row.get("content") is None:
            return row
        number = source.execute("SELECT application_number FROM tblApplications"
                                " WHERE application_id = ?",
                                (row["application_id"],)).fetchone()
        stored = self.files.upload_document(number[0] if number else "unfiled",
                                            row["file_name"], row["content"])
        return {**row, **stored, "content": None}

    # --- status ----------------------------------------------------------

    def status(self) -> dict:
        row = self.conn.execute(
            "SELECT site_id, hydrated, last_pull, last_push, last_error, last_error_at"
            " FROM _sync_state WHERE id = 1").fetchone()
        return {
            "site_url": self.config.site_url,
            "site_id": row[0],
            "hydrated": bool(row[1]),
            "last_pull": row[2],
            "last_push": row[3],
            "last_error": row[4],
            "last_error_at": row[5],
            "pending": self.pending_count(),
            "lists": len(self.specs),
        }
