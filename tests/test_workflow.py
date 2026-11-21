"""The status machine, end to end, without the UI."""

from __future__ import annotations

from app import auth, db, seed, workflow


def user(username: str) -> dict:
    u = auth._load(username)
    u["permissions"] = auth.permissions(u["role_name"])
    return u


def new_application(operator: dict) -> int:
    service_id, dept_id = db.one(
        "SELECT service_id, department_id FROM tblServiceMaster LIMIT 1")
    return db.execute(
        "INSERT INTO tblApplications(application_number, applicant_name, district_id,"
        " department_id, service_id, status, created_by, created_at)"
        " VALUES (?, 'Test Applicant', ?, ?, ?, 'Draft', ?, datetime('now'))",
        (f"TEST/{db.scalar('SELECT COUNT(*) FROM tblApplications') + 1}",
         operator["district_id"], dept_id, service_id, operator["user_id"]))


def status(app_id: int) -> tuple[str, str | None]:
    row = db.one("SELECT status, current_level FROM tblApplications"
                 " WHERE application_id = ?", (app_id,))
    return row["status"], row["current_level"]


def marks(result: str = "Pass") -> list[dict]:
    return [{"item_code": c, "item_text": t, "weight": w,
             "result": result if c == "QAP-01" else "Pass", "comment": "x"}
            for c, t, w in seed.CHECKLIST]


def test_happy_path_through_every_level_then_lock_unlock_relock() -> None:
    op, ver = user("operator.patna"), user("verifier.patna")
    app_id = new_application(op)
    workflow.submit(app_id, op)
    assert status(app_id) == ("Submitted", None)

    result, score = workflow.record_verification(app_id, ver["user_id"], marks(),
                                                 "ok", ver)
    assert (result, score) == ("Pass", 100.0)
    assert status(app_id) == ("Under Verification", "District Reviewer")

    actors = {"District Reviewer": "reviewer.patna",
              "District Approver": "distadmin.patna",
              "State Reviewer": "stateadmin", "State Approval": "stateadmin"}
    for level in workflow.LEVELS:
        actor = user(actors[level])
        assert workflow.LEVEL_PERMISSION[level] in actor["permissions"]
        workflow.decide(app_id, level, "Approve", "", actor)
    assert status(app_id) == ("Approved", "Completed")

    admin = user("distadmin.patna")
    workflow.lock(app_id, admin)
    assert status(app_id)[0] == "Locked"
    workflow.request_unlock(app_id, "Name spelling", admin)
    lock_id = db.scalar("SELECT MAX(lock_id) FROM tblLockUnlock WHERE application_id = ?",
                        (app_id,))
    workflow.decide_unlock(lock_id, True, user("stateadmin"))
    assert status(app_id)[0] == "Approved"
    workflow.relock(lock_id, admin)
    assert status(app_id)[0] == "Locked"


def test_failed_verification_raises_correction_and_comes_back() -> None:
    op, ver = user("operator.patna"), user("verifier.patna")
    app_id = new_application(op)
    workflow.submit(app_id, op)
    result, score = workflow.record_verification(app_id, ver["user_id"],
                                                 marks("Fail"), "", ver)
    assert result == "Fail" and score == 85.0
    assert status(app_id) == ("Correction Required", None)
    cid = db.scalar("SELECT MAX(correction_id) FROM tblCorrections"
                    " WHERE application_id = ?", (app_id,))
    assert db.scalar("SELECT assigned_to FROM tblCorrections WHERE correction_id = ?",
                     (cid,)) == op["user_id"]
    workflow.respond_correction(cid, "Fixed the name", op)
    # Back for re-verification: in verification, no approval level yet.
    assert status(app_id) == ("Under Verification", None)


def test_send_back_and_reject_and_escalate() -> None:
    op, ver = user("operator.patna"), user("verifier.patna")
    rev = user("reviewer.patna")

    a = new_application(op); workflow.submit(a, op)
    workflow.record_verification(a, ver["user_id"], marks(), "", ver)
    workflow.decide(a, "District Reviewer", "Send Back", "Wrong block", rev)
    assert status(a)[0] == "Correction Required"

    b = new_application(op); workflow.submit(b, op)
    workflow.record_verification(b, ver["user_id"], marks(), "", ver)
    workflow.decide(b, "District Reviewer", "Reject", "Duplicate", rev)
    assert status(b) == ("Rejected", "District Reviewer")

    c = new_application(op); workflow.submit(c, op)
    workflow.record_verification(c, ver["user_id"], marks(), "", ver)
    workflow.decide(c, "District Reviewer", "Escalate", "Urgent", rev)
    assert status(c) == ("Under Verification", "District Approver")


def test_every_action_lands_in_the_audit_trail() -> None:
    before = db.scalar("SELECT COUNT(*) FROM tblAuditLogs")
    op = user("operator.patna")
    app_id = new_application(op)
    workflow.submit(app_id, op)
    assert db.scalar("SELECT COUNT(*) FROM tblAuditLogs") > before


def test_scope_keeps_districts_apart() -> None:
    import streamlit as st

    st.session_state["rtps_user"] = user("operator.patna")
    clause, params = auth.scope_clause()
    patna = db.scalar(f"SELECT COUNT(*) FROM tblApplications a WHERE {clause}", params)
    other = db.scalar(
        f"SELECT COUNT(*) FROM tblApplications a WHERE {clause}"
        " AND a.district_id <> ?", params + [user("operator.patna")["district_id"]])
    assert patna > 0 and other == 0
    st.session_state["rtps_user"] = user("stateadmin")
    clause, params = auth.scope_clause()
    assert db.scalar(f"SELECT COUNT(*) FROM tblApplications a WHERE {clause}",
                     params) == db.scalar("SELECT COUNT(*) FROM tblApplications")
