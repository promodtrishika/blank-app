"""SharePoint as the database, tested against an HTTP-level fake of Graph."""

from __future__ import annotations

import os
import sqlite3

import pytest
from streamlit.testing.v1 import AppTest

from fake_graph import SECRET, FakeGraph
from app import db
from app.db import SCHEMA
from app.seed import seed_all
from app.sharepoint import config as sp_config
from app.sharepoint.config import SharePointConfig
from app.sharepoint.graph import GraphClient, GraphError
from app.sharepoint.store import SharePointStore

GRAPH, LOGIN = "https://graph.fake/v1.0", "https://login.fake"


def make_config(**over) -> SharePointConfig:
    base = dict(tenant_id="tenant", client_id="client", client_secret=SECRET,
                site_hostname="contoso.sharepoint.com", site_path="/sites/RTPS-QAP",
                graph_url=GRAPH, login_url=LOGIN)
    base.update(over)
    return SharePointConfig(**base)


def demo_source() -> sqlite3.Connection:
    src = sqlite3.connect(":memory:")
    src.row_factory = sqlite3.Row
    src.executescript(SCHEMA)
    seed_all(src)
    return src


def new_cache(tmp_path, name="cache.db") -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / name)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


@pytest.fixture
def fake():
    return FakeGraph()


@pytest.fixture
def sleeps():
    return []


@pytest.fixture
def client(fake, sleeps):
    return GraphClient(make_config(), session=fake.session(), sleep=sleeps.append)


@pytest.fixture
def loaded(fake, client, tmp_path):
    """A provisioned site holding the demo data, and a hydrated cache."""
    cache = new_cache(tmp_path)
    store = SharePointStore(cache, client, make_config(), SCHEMA)
    store.install()
    store.provision()
    store.migrate_from(demo_source(), progress=lambda m: None)
    store.hydrate()
    return store


# --- provisioning ------------------------------------------------------

def test_provision_creates_every_list_and_both_libraries(fake, client, tmp_path):
    store = SharePointStore(new_cache(tmp_path), client, make_config(), SCHEMA)
    made = store.provision()
    names = {l["displayName"] for l in fake.lists.values()}
    assert len([n for n in names if n.startswith("RTPS_")]) == 24
    assert {"RTPS Documents", "RTPS Reports"} <= names
    assert len(made) == 26
    assert store.provision() == []                     # running again changes nothing


def test_provision_adds_a_missing_column(fake, client, tmp_path):
    store = SharePointStore(new_cache(tmp_path), client, make_config(), SCHEMA)
    store.provision()
    del fake.list_by_name("RTPS_Applications")["columns"]["Score"]
    assert store.provision() == ["column RTPS_Applications.Score"]


def test_bad_secret_is_reported_not_swallowed(fake):
    bad = GraphClient(make_config(client_secret="wrong"), session=fake.session())
    with pytest.raises(GraphError) as err:
        bad.site_id()
    assert err.value.status == 401 and err.value.code == "invalid_client"


def test_wrong_site_path_is_a_404(fake):
    c = GraphClient(make_config(site_path="/sites/Nope"), session=fake.session())
    with pytest.raises(GraphError) as err:
        c.site_id()
    assert err.value.status == 404


# --- round trip ----------------------------------------------------------

def test_every_row_survives_the_round_trip(loaded):
    src = demo_source()
    for table, spec in loaded.specs.items():
        cols = [c.name for c in spec.columns]
        a = [tuple(r) for r in src.execute(
            f"SELECT {', '.join(cols)} FROM {table} ORDER BY rowid")]
        b = [tuple(r) for r in loaded.conn.execute(
            f"SELECT {', '.join(cols)} FROM {table} ORDER BY rowid")]
        assert a == b, table


def test_password_hashes_never_reach_sharepoint(fake, loaded):
    for item in fake.items("RTPS_Users"):
        assert "PasswordHash" not in item and "Salt" not in item
    row = loaded.conn.execute("SELECT password_hash FROM tblUsers LIMIT 1").fetchone()
    assert row[0] == "!"                               # matches no password


def test_migrating_twice_is_refused(loaded):
    with pytest.raises(RuntimeError, match="already has items"):
        loaded.migrate_from(demo_source(), progress=lambda m: None)


# --- writes go to SharePoint -------------------------------------------

def test_insert_update_delete_reach_sharepoint(fake, loaded):
    c = loaded.conn
    c.execute("INSERT INTO tblNotifications(user_id, event, message, sent_time)"
              " VALUES (1, 'New Submission', 'hello', datetime('now'))")
    nid = c.execute("SELECT MAX(notification_id) FROM tblNotifications").fetchone()[0]
    c.commit()
    assert loaded.pending_count() == 1
    assert loaded.push() == {"pushed": 1, "failed": 0}
    item = next(i for i in fake.items("RTPS_Notifications") if i["RecordId"] == nid)
    assert item["Message"] == "hello" and item["Title"] == "New Submission"

    c.execute("UPDATE tblNotifications SET message = 'edited' WHERE notification_id = ?",
              (nid,))
    c.commit()
    loaded.push()
    item = next(i for i in fake.items("RTPS_Notifications") if i["RecordId"] == nid)
    assert item["Message"] == "edited"

    c.execute("DELETE FROM tblNotifications WHERE notification_id = ?", (nid,))
    c.commit()
    loaded.push()
    assert not any(i["RecordId"] == nid for i in fake.items("RTPS_Notifications"))
    assert loaded.pending_count() == 0


def test_dates_are_stored_as_sharepoint_dates(fake, loaded):
    item = next(i for i in fake.items("RTPS_Applications") if i["RecordId"] == 1)
    assert item["CreatedAt"].endswith("Z") and "T" in item["CreatedAt"]
    assert item["SubmissionDate"].endswith("T00:00:00Z")


def test_long_text_and_255_limit(fake, loaded):
    c = loaded.conn
    long = "x" * 900
    c.execute("INSERT INTO tblAuditLogs(username, activity, module, new_value, timestamp)"
              " VALUES ('t', 'Long', 'Test', ?, datetime('now'))", (long,))
    c.commit()
    assert loaded.push()["failed"] == 0
    item = fake.items("RTPS_AuditLogs")[-1]
    assert item["NewValue"] == long                   # multi-line column: kept whole


def test_changes_wait_while_sharepoint_is_down_then_go(fake, loaded):
    c = loaded.conn
    c.execute("UPDATE tblApplications SET remarks = 'offline edit' WHERE application_id = 3")
    c.commit()
    fake.fail_status = 503
    result = loaded.push()
    assert result["pushed"] == 0 and loaded.pending_count() == 1
    assert loaded.status()["last_error"]
    fake.fail_status = None
    assert loaded.push() == {"pushed": 1, "failed": 0}
    assert loaded.status()["last_error"] is None
    item = next(i for i in fake.items("RTPS_Applications") if i["RecordId"] == 3)
    assert item["Remarks"] == "offline edit"


def test_throttling_is_retried_with_retry_after(fake, loaded, sleeps):
    c = loaded.conn
    for i in range(30):
        c.execute("INSERT INTO tblAuditLogs(username, activity, module, timestamp)"
                  " VALUES ('t', ?, 'Test', datetime('now'))", (f"bulk {i}",))
    c.commit()
    fake.throttle_next = 2                # whole $batch calls refused
    fake.throttle_batch_items = 5         # and some items inside a batch
    assert loaded.push() == {"pushed": 30, "failed": 0}
    assert sleeps, "the client waited before retrying"


def test_item_deleted_in_sharepoint_while_edited_here_is_recreated(fake, loaded):
    sp_id = loaded._sp_id("tblApplications", 4)
    fake.delete_item_directly("RTPS_Applications", sp_id)
    loaded.conn.execute("UPDATE tblApplications SET remarks = 'still here'"
                        " WHERE application_id = 4")
    loaded.conn.commit()
    loaded.push()                          # PATCH 404: forgets the old item
    loaded.conn.execute("UPDATE tblApplications SET remarks = 'still here'"
                        " WHERE application_id = 4")
    loaded.conn.commit()
    loaded.push()                          # and creates it again
    assert any(i["RecordId"] == 4 and i["Remarks"] == "still here"
               for i in fake.items("RTPS_Applications"))


# --- changes made in SharePoint reach the portal ------------------------

def test_edit_add_delete_in_sharepoint_are_pulled(fake, loaded):
    sp_id = loaded._sp_id("tblApplications", 7)
    fake.edit_item_directly("RTPS_Applications", sp_id, {"Remarks": "edited in SharePoint"})
    new_sp = fake.add_item_directly("RTPS_DepartmentMaster",
                                    {"Title": "Education", "DepartmentName": "Education",
                                     "Status": "Active"})
    gone_sp = loaded._sp_id("tblNotifications", 1)
    fake.delete_item_directly("RTPS_Notifications", gone_sp)

    loaded.pull()
    c = loaded.conn
    assert c.execute("SELECT remarks FROM tblApplications WHERE application_id = 7"
                     ).fetchone()[0] == "edited in SharePoint"
    row = c.execute("SELECT department_id FROM tblDepartmentMaster"
                    " WHERE department_name = 'Education'").fetchone()
    assert row is not None
    # The portal gave it an id and wrote it back to SharePoint.
    item = fake.list_by_name("RTPS_DepartmentMaster")["items"][new_sp]["fields"]
    assert item["RecordId"] == row[0]
    assert c.execute("SELECT COUNT(*) FROM tblNotifications WHERE notification_id = 1"
                     ).fetchone()[0] == 0
    # Pulling again changes nothing and creates no duplicate.
    loaded.pull()
    assert c.execute("SELECT COUNT(*) FROM tblDepartmentMaster"
                     " WHERE department_name = 'Education'").fetchone()[0] == 1


def test_a_pending_local_change_is_not_overwritten_by_a_pull(fake, loaded):
    sp_id = loaded._sp_id("tblApplications", 9)
    loaded.conn.execute("UPDATE tblApplications SET remarks = 'mine' WHERE application_id = 9")
    loaded.conn.commit()
    fake.edit_item_directly("RTPS_Applications", sp_id, {"Remarks": "theirs"})
    loaded.pull()
    assert loaded.conn.execute("SELECT remarks FROM tblApplications"
                               " WHERE application_id = 9").fetchone()[0] == "mine"


def test_expired_delta_token_falls_back_to_a_full_read(fake, loaded):
    sp_id = loaded._sp_id("tblApplications", 11)
    fake.edit_item_directly("RTPS_Applications", sp_id, {"Remarks": "after expiry"})
    fake.expire_delta_tokens()
    loaded.pull()
    assert loaded.conn.execute("SELECT remarks FROM tblApplications"
                               " WHERE application_id = 11").fetchone()[0] == "after expiry"
    assert loaded.conn.execute("SELECT COUNT(*) FROM tblApplications").fetchone()[0] == 430


def test_a_restarted_portal_keeps_its_queue_and_catches_up(fake, client, loaded, tmp_path):
    loaded.conn.execute("UPDATE tblApplications SET remarks = 'queued' WHERE application_id = 2")
    loaded.conn.commit()
    path = loaded.conn.execute("PRAGMA database_list").fetchone()[2]
    loaded.conn.close()
    reopened = sqlite3.connect(path)
    reopened.row_factory = sqlite3.Row
    again = SharePointStore(reopened, client, make_config(), SCHEMA)
    again.install()
    assert not again.needs_hydrate()
    assert again.pending_count() == 1
    again.push()
    assert any(i["RecordId"] == 2 and i["Remarks"] == "queued"
               for i in fake.items("RTPS_Applications"))


# --- document and report libraries --------------------------------------

def test_documents_move_into_the_library_with_versions(fake, loaded):
    c = loaded.conn
    for version, data in ((1, b"first version"), (2, b"second version")):
        c.execute("INSERT INTO tblDocuments(application_id, file_name, file_type, file_size,"
                  " version, uploaded_by, upload_time, verified, content)"
                  " VALUES (1, 'proof.pdf', 'PDF', ?, ?, 1, datetime('now'), 0, ?)",
                  (len(data), version, data))
        c.commit()
        loaded.push()
    rows = c.execute("SELECT content, sp_item_id, sp_version_id, web_url FROM tblDocuments"
                     " WHERE file_name = 'proof.pdf' ORDER BY version").fetchall()
    assert all(r["content"] is None for r in rows)            # bytes left the portal
    assert rows[0]["sp_item_id"] == rows[1]["sp_item_id"]     # one SharePoint file…
    assert rows[0]["sp_version_id"] != rows[1]["sp_version_id"]   # …two versions
    number = c.execute("SELECT application_number FROM tblApplications"
                       " WHERE application_id = 1").fetchone()[0]
    assert number.replace("/", "-") in rows[0]["web_url"]
    files = loaded.files
    assert files.download_document(rows[0]["sp_item_id"], rows[0]["sp_version_id"]) == b"first version"
    assert files.download_document(rows[1]["sp_item_id"], rows[1]["sp_version_id"]) == b"second version"
    item = next(i for i in fake.items("RTPS_Documents")
                if i["FileName"] == "proof.pdf" and i["RtpsVersion"] == 2)
    assert item["SpItemId"] == rows[1]["sp_item_id"]


def test_reports_are_saved_to_the_reports_library(fake, loaded):
    url = loaded.files.save_report("Pending Report", "pending-report 2026-11-21.pdf", b"%PDF")
    drive = next(d for d in fake.drives.values() if d["name"] == "RTPS Reports")
    assert "Pending Report/pending-report 2026-11-21.pdf" in drive["paths"]
    assert url and "RTPS%20Reports" in url


# --- the provisioning command ------------------------------------------

def test_provision_command_loads_reference_data_only(fake, monkeypatch, capsys):
    env(monkeypatch)
    from app.sharepoint import provision

    assert provision.run([], session=fake.session(), sleep=lambda s: None) == 0
    assert len(fake.items("RTPS_Roles")) == 8
    assert len(fake.items("RTPS_DistrictMaster")) == 38
    assert fake.items("RTPS_Applications") == []
    assert fake.items("RTPS_Users") == []
    assert provision.run([], session=fake.session(), sleep=lambda s: None) == 0
    assert "already there" in capsys.readouterr().out
    assert len(fake.items("RTPS_Roles")) == 8          # not loaded twice


def test_provision_command_migrates_a_portal_database(fake, monkeypatch, tmp_path):
    env(monkeypatch)
    from app.sharepoint import provision

    path = tmp_path / "old.db"
    src = sqlite3.connect(path)
    src.row_factory = sqlite3.Row
    src.executescript(SCHEMA)
    seed_all(src)
    src.commit()
    src.close()
    assert provision.run(["--migrate", str(path)], session=fake.session(),
                         sleep=lambda s: None) == 0
    assert len(fake.items("RTPS_Applications")) == 430


def test_provision_command_explains_a_bad_secret(fake, monkeypatch, capsys):
    env(monkeypatch, RTPS_SP_CLIENT_SECRET="wrong")
    from app.sharepoint import provision

    assert provision.run([], session=fake.session(), sleep=lambda s: None) == 1
    assert "client secret" in capsys.readouterr().err


# --- the portal running on SharePoint ---------------------------------

def env(monkeypatch, **over):
    values = {
        "RTPS_SP_ENABLED": "1", "RTPS_SP_TENANT_ID": "tenant",
        "RTPS_SP_CLIENT_ID": "client", "RTPS_SP_CLIENT_SECRET": SECRET,
        "RTPS_SP_SITE_HOSTNAME": "contoso.sharepoint.com",
        "RTPS_SP_SITE_PATH": "/sites/RTPS-QAP", "RTPS_SP_GRAPH_URL": GRAPH,
        "RTPS_SP_LOGIN_URL": LOGIN,
    }
    values.update(over)
    for k, v in values.items():
        monkeypatch.setenv(k, v)


@pytest.fixture
def portal(fake, monkeypatch, tmp_path):
    """The whole portal, configured for SharePoint and pointed at the fake."""
    env(monkeypatch, RTPS_SP_CACHE_PATH=str(tmp_path / "portal-cache.db"),
        RTPS_SP_BOOTSTRAP_ADMIN_EMAIL="first.admin@contoso.gov.in")
    store = SharePointStore(sqlite3.connect(":memory:"),
                            GraphClient(make_config(), session=fake.session()),
                            make_config(), SCHEMA)
    store.provision()
    store.migrate_from(demo_source(), progress=lambda m: None)
    monkeypatch.setattr(GraphClient, "session_factory", fake.session)
    monkeypatch.setattr(GraphClient, "sleep_override", lambda s: None)
    db._runtime.clear()
    yield fake
    db.flush()
    db._runtime.clear()


def session_user(username: str) -> dict:
    from app import auth

    user = auth._load(username)
    user["permissions"] = auth.permissions(user["role_name"])
    return user


def test_portal_runs_on_sharepoint(portal):
    assert db.mode() == "sharepoint"
    assert db.scalar("SELECT COUNT(*) FROM tblApplications") == 430
    assert sp_config.load().site_url == "https://contoso.sharepoint.com/sites/RTPS-QAP"


def test_a_workflow_step_lands_in_sharepoint(portal):
    from app import workflow

    op = session_user("operator.patna")
    app_id = db.scalar("SELECT application_id FROM tblApplications WHERE status = 'Draft'"
                       " LIMIT 1")
    workflow.submit(app_id, op)
    db.flush()
    item = next(i for i in portal.items("RTPS_Applications") if i["RecordId"] == app_id)
    assert item["Status"] == "Submitted"
    assert any(i["Activity"].startswith("Status") for i in portal.items("RTPS_AuditLogs"))


def test_passwords_are_off_in_sharepoint_mode(portal):
    from app import auth

    user, problem = auth.authenticate("operator.patna", "Rtps@2026")
    assert user is None and problem == "Wrong password."
    assert not auth.passwords_allowed()


def test_microsoft_365_accounts_map_to_portal_users_by_email(portal):
    from app import auth

    email = db.scalar("SELECT email FROM tblUsers WHERE username = 'verifier.gaya'")
    assert auth.user_for_email(email.upper())["username"] == "verifier.gaya"
    assert auth.user_for_email("nobody@contoso.gov.in") is None


def test_bootstrap_admin_only_while_no_super_admin_exists(portal):
    from app import auth

    # The demo data has a Super Admin, so the bootstrap address gets nothing.
    assert auth.bootstrap_admin("first.admin@contoso.gov.in", "First Admin") is None
    db.execute("UPDATE tblUsers SET status = 'Disabled' WHERE username = 'superadmin'")
    assert auth.bootstrap_admin("someone.else@contoso.gov.in", "X") is None
    made = auth.bootstrap_admin("first.admin@contoso.gov.in", "First Admin")
    assert made["role_name"] == "Super Admin"
    db.flush()
    assert any(i.get("Email") == "first.admin@contoso.gov.in"
               for i in portal.items("RTPS_Users"))


def test_login_screen_asks_for_microsoft_365(portal):
    at = AppTest.from_file("streamlit_app.py", default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert not at.text_input, "no password form in SharePoint mode"
    assert any("Microsoft 365 sign-in is not configured" in e.value for e in at.error)


ROLES = ["superadmin", "stateadmin", "divadmin.patna", "distadmin.patna",
         "reviewer.patna", "verifier.patna", "operator.patna", "readonly"]


def test_every_screen_renders_on_sharepoint_for_every_role(portal):
    from app.navigation import PAGES

    rendered = expected = 0
    for username in ROLES:
        user = session_user(username)
        for path, title, _i, codes, _g in PAGES:
            if not any(c in user["permissions"] for c in codes):
                continue
            expected += 1
            at = AppTest.from_file(path, default_timeout=60)
            at.session_state["rtps_user"] = user
            at.run()
            assert not at.exception, (username, title, [e.value for e in at.exception])
            rendered += 1
    assert rendered == expected and expected > 60


@pytest.fixture
def empty_portal(fake, monkeypatch, tmp_path):
    """A freshly provisioned site: reference data, one admin, no records."""
    env(monkeypatch, RTPS_SP_CACHE_PATH=str(tmp_path / "empty-cache.db"),
        RTPS_SP_BOOTSTRAP_ADMIN_EMAIL="first.admin@contoso.gov.in")
    monkeypatch.setattr(GraphClient, "session_factory", fake.session)
    monkeypatch.setattr(GraphClient, "sleep_override", lambda s: None)
    from app.sharepoint import provision

    assert provision.run([], session=fake.session(), sleep=lambda s: None) == 0
    db._runtime.clear()
    yield fake
    db.flush()
    db._runtime.clear()


def test_every_screen_renders_on_an_empty_site(empty_portal):
    from app import auth
    from app.navigation import PAGES

    admin = auth.bootstrap_admin("first.admin@contoso.gov.in", "First Admin")
    admin["permissions"] = auth.permissions(admin["role_name"])
    assert db.scalar("SELECT COUNT(*) FROM tblApplications") == 0
    for path, title, *_ in PAGES:
        at = AppTest.from_file(path, default_timeout=60)
        at.session_state["rtps_user"] = admin
        at.run()
        assert not at.exception, (title, [e.value for e in at.exception])
