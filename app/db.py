"""SQLite store for the RTPS QAP prototype.

Table names and columns mirror the blueprint's SQL Server schema, so the DDL
below doubles as the reference for the production database. The file is
created and seeded on first run.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("RTPS_QAP_DB", ROOT / "rtps_qap.db"))

# One connection serves every session; this keeps them from interleaving.
LOCK = threading.RLock()

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tblRoles (
    role_id        INTEGER PRIMARY KEY,
    role_name      TEXT NOT NULL UNIQUE,
    role_level     INTEGER NOT NULL,
    scope          TEXT NOT NULL,          -- state | division | district | none
    description    TEXT
);

CREATE TABLE IF NOT EXISTS tblPermissions (
    permission_id   INTEGER PRIMARY KEY,
    permission_code TEXT NOT NULL UNIQUE,
    module          TEXT NOT NULL,
    description     TEXT
);

CREATE TABLE IF NOT EXISTS tblRolePermissions (
    role_id       INTEGER NOT NULL REFERENCES tblRoles(role_id),
    permission_id INTEGER NOT NULL REFERENCES tblPermissions(permission_id),
    PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE IF NOT EXISTS tblDivisionMaster (
    division_id   INTEGER PRIMARY KEY,
    division_name TEXT NOT NULL UNIQUE,
    status        TEXT NOT NULL DEFAULT 'Active'
);

CREATE TABLE IF NOT EXISTS tblDistrictMaster (
    district_id   INTEGER PRIMARY KEY,
    district_name TEXT NOT NULL UNIQUE,
    division_id   INTEGER NOT NULL REFERENCES tblDivisionMaster(division_id),
    status        TEXT NOT NULL DEFAULT 'Active'
);

CREATE TABLE IF NOT EXISTS tblBlockMaster (
    block_id    INTEGER PRIMARY KEY,
    block_name  TEXT NOT NULL,
    district_id INTEGER NOT NULL REFERENCES tblDistrictMaster(district_id),
    status      TEXT NOT NULL DEFAULT 'Active'
);

CREATE TABLE IF NOT EXISTS tblOfficeMaster (
    office_id   INTEGER PRIMARY KEY,
    office_name TEXT NOT NULL,
    district_id INTEGER NOT NULL REFERENCES tblDistrictMaster(district_id),
    status      TEXT NOT NULL DEFAULT 'Active'
);

CREATE TABLE IF NOT EXISTS tblDepartmentMaster (
    department_id   INTEGER PRIMARY KEY,
    department_name TEXT NOT NULL UNIQUE,
    status          TEXT NOT NULL DEFAULT 'Active'
);

CREATE TABLE IF NOT EXISTS tblServiceMaster (
    service_id    INTEGER PRIMARY KEY,
    service_name  TEXT NOT NULL UNIQUE,
    department_id INTEGER NOT NULL REFERENCES tblDepartmentMaster(department_id),
    sla_days      INTEGER NOT NULL DEFAULT 15,
    status        TEXT NOT NULL DEFAULT 'Active'
);

CREATE TABLE IF NOT EXISTS tblUsers (
    user_id       INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL,
    employee_name TEXT NOT NULL,
    designation   TEXT,
    mobile        TEXT,
    email         TEXT,
    division_id   INTEGER REFERENCES tblDivisionMaster(division_id),
    district_id   INTEGER REFERENCES tblDistrictMaster(district_id),
    status        TEXT NOT NULL DEFAULT 'Active',
    last_login    TEXT,
    created_at    TEXT NOT NULL,
    created_by    TEXT
);

CREATE TABLE IF NOT EXISTS tblUserRoles (
    user_id INTEGER NOT NULL REFERENCES tblUsers(user_id),
    role_id INTEGER NOT NULL REFERENCES tblRoles(role_id),
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE IF NOT EXISTS tblApplications (
    application_id     INTEGER PRIMARY KEY,
    application_number TEXT NOT NULL UNIQUE,
    applicant_name     TEXT NOT NULL,
    district_id        INTEGER NOT NULL REFERENCES tblDistrictMaster(district_id),
    subdivision        TEXT,
    block_id           INTEGER REFERENCES tblBlockMaster(block_id),
    office_id          INTEGER REFERENCES tblOfficeMaster(office_id),
    department_id      INTEGER NOT NULL REFERENCES tblDepartmentMaster(department_id),
    service_id         INTEGER NOT NULL REFERENCES tblServiceMaster(service_id),
    submission_date    TEXT,
    status             TEXT NOT NULL DEFAULT 'Draft',
    current_level      TEXT,
    score              REAL,
    remarks            TEXT,
    is_locked          INTEGER NOT NULL DEFAULT 0,
    created_by         INTEGER REFERENCES tblUsers(user_id),
    created_at         TEXT NOT NULL,
    updated_at         TEXT,
    submitted_at       TEXT,
    approved_at        TEXT
);

CREATE TABLE IF NOT EXISTS tblApplicationDetails (
    detail_id      INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES tblApplications(application_id),
    field_name     TEXT NOT NULL,
    field_value    TEXT
);

CREATE TABLE IF NOT EXISTS tblVerification (
    verification_id    INTEGER PRIMARY KEY,
    application_id     INTEGER NOT NULL REFERENCES tblApplications(application_id),
    verifier_id        INTEGER REFERENCES tblUsers(user_id),
    score              REAL,
    result             TEXT,              -- Pass | Fail
    quality_assessment TEXT,
    recommendation     TEXT,
    remarks            TEXT,
    verified_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tblVerificationChecklist (
    checklist_id    INTEGER PRIMARY KEY,
    verification_id INTEGER NOT NULL REFERENCES tblVerification(verification_id),
    item_code       TEXT NOT NULL,
    item_text       TEXT NOT NULL,
    weight          INTEGER NOT NULL,
    result          TEXT NOT NULL,         -- Pass | Fail | NA
    comment         TEXT
);

CREATE TABLE IF NOT EXISTS tblCorrections (
    correction_id   INTEGER PRIMARY KEY,
    application_id  INTEGER NOT NULL REFERENCES tblApplications(application_id),
    raised_by       INTEGER REFERENCES tblUsers(user_id),
    assigned_to     INTEGER REFERENCES tblUsers(user_id),
    reason          TEXT NOT NULL,
    comments        TEXT,
    status          TEXT NOT NULL DEFAULT 'Open',
    raised_at       TEXT NOT NULL,
    responded_at    TEXT,
    closed_at       TEXT,
    closure_remarks TEXT
);

CREATE TABLE IF NOT EXISTS tblCorrectionHistory (
    history_id    INTEGER PRIMARY KEY,
    correction_id INTEGER NOT NULL REFERENCES tblCorrections(correction_id),
    action        TEXT NOT NULL,
    actor_id      INTEGER REFERENCES tblUsers(user_id),
    comments      TEXT,
    action_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tblApproval (
    approval_id    INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES tblApplications(application_id),
    current_level  TEXT NOT NULL,
    approver_id    INTEGER REFERENCES tblUsers(user_id),
    decision       TEXT NOT NULL DEFAULT 'Pending',
    remarks        TEXT,
    approval_date  TEXT
);

CREATE TABLE IF NOT EXISTS tblApprovalHistory (
    history_id     INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES tblApplications(application_id),
    level          TEXT NOT NULL,
    approver_id    INTEGER REFERENCES tblUsers(user_id),
    decision       TEXT NOT NULL,
    remarks        TEXT,
    action_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tblLockUnlock (
    lock_id              INTEGER PRIMARY KEY,
    application_id       INTEGER NOT NULL REFERENCES tblApplications(application_id),
    lock_date            TEXT,
    locked_by            INTEGER REFERENCES tblUsers(user_id),
    unlock_reason        TEXT,
    unlock_requested_by  INTEGER REFERENCES tblUsers(user_id),
    unlock_requested_at  TEXT,
    unlock_status        TEXT,             -- Requested | Approved | Rejected | Relocked
    unlock_approved_by   INTEGER REFERENCES tblUsers(user_id),
    unlock_date          TEXT,
    relock_date          TEXT
);

CREATE TABLE IF NOT EXISTS tblDocuments (
    document_id    INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES tblApplications(application_id),
    file_name      TEXT NOT NULL,
    file_type      TEXT NOT NULL,
    file_size      INTEGER NOT NULL DEFAULT 0,
    version        INTEGER NOT NULL DEFAULT 1,
    uploaded_by    INTEGER REFERENCES tblUsers(user_id),
    upload_time    TEXT NOT NULL,
    verified       INTEGER NOT NULL DEFAULT 0,
    content        BLOB,                  -- local mode; empty once in SharePoint
    sp_item_id     TEXT,                  -- SharePoint driveItem id
    sp_version_id  TEXT,                  -- the SharePoint version this row is
    web_url        TEXT
);

CREATE TABLE IF NOT EXISTS tblNotifications (
    notification_id INTEGER PRIMARY KEY,
    user_id         INTEGER REFERENCES tblUsers(user_id),
    application_id  INTEGER REFERENCES tblApplications(application_id),
    event           TEXT NOT NULL,
    message         TEXT NOT NULL,
    channel         TEXT NOT NULL DEFAULT 'In-App',
    type            TEXT NOT NULL DEFAULT 'Info',
    status          TEXT NOT NULL DEFAULT 'Sent',
    sent_time       TEXT NOT NULL,
    read_flag       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tblAuditLogs (
    audit_id   INTEGER PRIMARY KEY,
    user_id    INTEGER REFERENCES tblUsers(user_id),
    username   TEXT,
    activity   TEXT NOT NULL,
    module     TEXT NOT NULL,
    entity     TEXT,
    entity_id  TEXT,
    old_value  TEXT,
    new_value  TEXT,
    ip_address TEXT,
    browser    TEXT,
    timestamp  TEXT NOT NULL
);

-- Not in the blueprint's table list: portal settings need somewhere to live.
CREATE TABLE IF NOT EXISTS tblSettings (
    setting_key   TEXT PRIMARY KEY,
    setting_value TEXT NOT NULL,
    label         TEXT NOT NULL,
    updated_at    TEXT,
    updated_by    TEXT
);

CREATE INDEX IF NOT EXISTS ix_app_status   ON tblApplications(status);
CREATE INDEX IF NOT EXISTS ix_app_district ON tblApplications(district_id);
CREATE INDEX IF NOT EXISTS ix_app_service  ON tblApplications(service_id);
CREATE INDEX IF NOT EXISTS ix_audit_time   ON tblAuditLogs(timestamp);
CREATE INDEX IF NOT EXISTS ix_notif_user   ON tblNotifications(user_id, read_flag);
"""


DEFAULT_SETTINGS = [
    ("session_timeout_minutes", "30", "Session timeout (minutes)"),
    ("password_min_length", "8", "Minimum password length"),
    ("mfa_required", "1", "Ask for a one-time passcode at sign-in"),
    ("notify_email", "1", "Send email notifications"),
    ("notify_sms", "1", "Send SMS notifications"),
    ("notify_inapp", "1", "Show in-app notifications"),
    ("sla_warning_days", "2", "Warn this many days before an SLA is breached"),
    ("qap_pass_score", "60", "Lowest QAP score that can pass verification"),
]


def setting(key: str, default: str | None = None) -> str | None:
    row = one("SELECT setting_value FROM tblSettings WHERE setting_key = ?", (key,))
    return row[0] if row else default


def hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """Bring a database made by an earlier version up to the current schema."""
    have = {r[1] for r in conn.execute("PRAGMA table_info(tblDocuments)")}
    for col in ("sp_item_id", "sp_version_id", "web_url"):
        if col not in have:
            conn.execute(f"ALTER TABLE tblDocuments ADD COLUMN {col} TEXT")


@st.cache_resource(show_spinner="Connecting to the portal's data…")
def _runtime():
    """The shared connection, and the SharePoint store when SharePoint is on."""
    from app.sharepoint import config as sp_config

    cfg = sp_config.load()
    if cfg is None:
        first_run = not DB_PATH.exists()
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        _add_missing_columns(conn)
        if first_run or not conn.execute("SELECT 1 FROM tblRoles LIMIT 1").fetchone():
            seed(conn)
        conn.executemany(
            "INSERT OR IGNORE INTO tblSettings(setting_key, setting_value, label)"
            " VALUES (?,?,?)", DEFAULT_SETTINGS)
        conn.commit()
        return conn, None
    return _open_sharepoint(cfg)


def _open_sharepoint(cfg):
    from app.sharepoint.graph import GraphClient, GraphError
    from app.sharepoint.store import SharePointStore

    data_dir = Path(os.environ.get("RTPS_DATA_DIR") or ROOT / ".rtps_cache")
    path = Path(cfg.cache_path) if cfg.cache_path else data_dir / "sharepoint.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _add_missing_columns(conn)
    store = SharePointStore(conn, GraphClient(cfg), cfg, SCHEMA, LOCK)
    store.install()
    had_data = bool(conn.execute("SELECT hydrated FROM _sync_state").fetchone()[0])
    try:
        if store.needs_hydrate():
            store.reset_cache()
            store.hydrate()
        else:
            store.push()
            store.pull()
    except GraphError as exc:
        if not had_data:
            raise RuntimeError(
                f"Could not load the portal's data from SharePoint ({exc}). Check the "
                "[sharepoint] settings and that the lists are provisioned.") from exc
        store._error(f"Working from the local copy until SharePoint answers: {exc}")
    conn.executemany(
        "INSERT OR IGNORE INTO tblSettings(setting_key, setting_value, label)"
        " VALUES (?,?,?)", DEFAULT_SETTINGS)
    conn.commit()
    try:
        store.push()
    except GraphError:
        pass
    return conn, store


def connect() -> sqlite3.Connection:
    """One connection for the whole app, shared across sessions."""
    return _runtime()[0]


def store():
    """The SharePoint store, or None in local mode."""
    return _runtime()[1]


def mode() -> str:
    return "sharepoint" if store() is not None else "local"


def flush() -> None:
    """Send queued changes to SharePoint. Called at the end of every page run."""
    s = store()
    if s is None:
        return
    try:
        s.push()
    except Exception as exc:  # recorded; the changes stay queued
        s._error(str(exc))


def refresh() -> None:
    """Pick up changes made in SharePoint, at most every pull interval."""
    s = store()
    if s is None:
        return
    try:
        s.pull_if_stale()
    except Exception as exc:
        s._error(str(exc))


def query(sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
    with LOCK:
        return connect().execute(sql, params).fetchall()


def one(sql: str, params: tuple | list = ()):
    with LOCK:
        return connect().execute(sql, params).fetchone()


def scalar(sql: str, params: tuple | list = (), default=0):
    row = one(sql, params)
    if row is None or row[0] is None:
        return default
    return row[0]


def execute(sql: str, params: tuple | list = ()) -> int:
    with LOCK:
        conn = connect()
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid


def frame(sql: str, params: tuple | list = ()):
    """A query as a DataFrame — with its columns even when there are no rows,
    so code that sorts or picks columns works on an empty result too."""
    import pandas as pd

    with LOCK:
        cur = connect().execute(sql, params)
        columns = [c[0] for c in cur.description or []]
        rows = cur.fetchall()
    return pd.DataFrame([tuple(r) for r in rows], columns=columns)


def seed(conn: sqlite3.Connection) -> None:
    """Fill a fresh database with masters, roles, demo users and history."""
    from app.seed import seed_all

    seed_all(conn)
