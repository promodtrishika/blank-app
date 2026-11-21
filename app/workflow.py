"""The status machine shared by every screen that moves an application.

One definition of what a status may become, which approval level comes next,
and which permission each level needs — so verification, correction,
approval and lock/unlock cannot disagree about the same record.
"""

from __future__ import annotations

from app import audit, db, notify

LEVELS = ["District Reviewer", "District Approver", "State Reviewer", "State Approval"]

LEVEL_PERMISSION = {
    "District Reviewer": "approve.district_review",
    "District Approver": "approve.district_approve",
    "State Reviewer": "approve.state_review",
    "State Approval": "approve.state_approve",
}

# What each status may become, and nothing else.
TRANSITIONS = {
    "Draft": ["Submitted"],
    "Submitted": ["Under Verification", "Correction Required"],
    "Under Verification": ["Approved", "Rejected", "Correction Required"],
    "Correction Required": ["Under Verification"],
    "Approved": ["Locked"],
    "Rejected": [],
    "Locked": ["Approved"],          # through an approved unlock request
}

APPROVAL_ACTIONS = ["Approve", "Reject", "Send Back", "Hold", "Escalate"]


def may_move(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, [])


def next_level(level: str | None) -> str | None:
    if level is None:
        return LEVELS[0]
    if level == "Completed" or level not in LEVELS:
        return None
    i = LEVELS.index(level)
    return LEVELS[i + 1] if i + 1 < len(LEVELS) else None


def set_status(application_id: int, status: str, level: str | None = None,
               remarks: str | None = None, user: dict | None = None,
               module: str = "Application Management") -> None:
    before = db.one("SELECT status, current_level FROM tblApplications"
                    " WHERE application_id = ?", (application_id,))
    db.execute(
        "UPDATE tblApplications SET status = ?, current_level = ?,"
        " remarks = COALESCE(?, remarks), updated_at = datetime('now'),"
        " is_locked = ? WHERE application_id = ?",
        (status, level, remarks, 1 if status == "Locked" else 0, application_id),
    )
    number = db.scalar("SELECT application_number FROM tblApplications"
                       " WHERE application_id = ?", (application_id,), default="")
    audit.log(
        f"Status → {status}", module, "tblApplications", number,
        old_value=f"{before['status']} / {before['current_level'] or '—'}" if before else None,
        new_value=f"{status} / {level or '—'}", user=user,
    )


def submit(application_id: int, user: dict) -> None:
    set_status(application_id, "Submitted", None, user=user)
    db.execute(
        "UPDATE tblApplications SET submitted_at = datetime('now'),"
        " submission_date = date('now') WHERE application_id = ?", (application_id,)
    )
    row = db.one(
        "SELECT a.application_number, a.district_id, u.user_id AS verifier"
        "  FROM tblApplications a"
        "  LEFT JOIN tblUsers u ON u.district_id = a.district_id"
        "  LEFT JOIN tblUserRoles ur ON ur.user_id = u.user_id"
        "  LEFT JOIN tblRoles r ON r.role_id = ur.role_id AND r.role_name = 'Verifier'"
        " WHERE a.application_id = ? AND r.role_name = 'Verifier' LIMIT 1",
        (application_id,),
    )
    if row:
        notify.send(row["verifier"], "New Submission",
                    f"{row['application_number']}: submitted and waiting for QAP verification.",
                    application_id, kind="Action")


def record_verification(application_id: int, verifier_id: int, marks: list[dict],
                        remarks: str, user: dict) -> tuple[str, float]:
    """Score the checklist, store it, and move the record accordingly."""
    total = float(sum(m["weight"] for m in marks if m["result"] == "Pass"))
    result = "Pass" if all(m["result"] != "Fail" for m in marks) else "Fail"
    quality = ("Excellent" if total >= 90 else "Good" if total >= 75
               else "Satisfactory" if total >= 60 else "Needs Improvement")
    vid = db.execute(
        "INSERT INTO tblVerification(application_id, verifier_id, score, result,"
        " quality_assessment, recommendation, remarks, verified_at)"
        " VALUES (?,?,?,?,?,?,?, datetime('now'))",
        (application_id, verifier_id, total, result, quality,
         "Forward for approval" if result == "Pass" else "Return for correction",
         remarks or None),
    )
    for m in marks:
        db.execute(
            "INSERT INTO tblVerificationChecklist(verification_id, item_code,"
            " item_text, weight, result, comment) VALUES (?,?,?,?,?,?)",
            (vid, m["item_code"], m["item_text"], m["weight"], m["result"],
             m.get("comment") or None),
        )
    db.execute("UPDATE tblApplications SET score = ? WHERE application_id = ?",
               (total, application_id))
    number = db.scalar("SELECT application_number FROM tblApplications"
                       " WHERE application_id = ?", (application_id,), default="")
    audit.log(f"Verification {result} ({total:.0f}/100)", "QAP Verification",
              "tblVerification", number, new_value=result, user=user)

    if result == "Pass":
        set_status(application_id, "Under Verification", LEVELS[0],
                   user=user, module="QAP Verification")
        db.execute(
            "INSERT INTO tblApproval(application_id, current_level, decision)"
            " VALUES (?,?, 'Pending')", (application_id, LEVELS[0]))
    else:
        failed = [m["item_text"] for m in marks if m["result"] == "Fail"]
        raise_correction(
            application_id,
            reason=failed[0] if failed else "Verification checklist not met",
            comments="Raised automatically from the failed verification checklist.",
            raised_by=verifier_id, user=user,
        )
    return result, total


def raise_correction(application_id: int, reason: str, comments: str,
                     raised_by: int, user: dict,
                     assigned_to: int | None = None) -> int:
    if assigned_to is None:
        assigned_to = db.scalar(
            "SELECT created_by FROM tblApplications WHERE application_id = ?",
            (application_id,), default=None)
    cid = db.execute(
        "INSERT INTO tblCorrections(application_id, raised_by, assigned_to, reason,"
        " comments, status, raised_at) VALUES (?,?,?,?,?,?, datetime('now'))",
        (application_id, raised_by, assigned_to, reason, comments,
         "Assigned" if assigned_to else "Open"),
    )
    db.execute(
        "INSERT INTO tblCorrectionHistory(correction_id, action, actor_id, comments,"
        " action_at) VALUES (?,?,?,?, datetime('now'))",
        (cid, "Raised", raised_by, comments),
    )
    set_status(application_id, "Correction Required", None, user=user,
               module="Correction Management")
    number = db.scalar("SELECT application_number FROM tblApplications"
                       " WHERE application_id = ?", (application_id,), default="")
    notify.send(assigned_to, "Correction Raised",
                f"{number}: correction raised — {reason}", application_id, kind="Action")
    return cid


def respond_correction(correction_id: int, comments: str, user: dict) -> None:
    row = db.one("SELECT application_id, raised_by FROM tblCorrections"
                 " WHERE correction_id = ?", (correction_id,))
    db.execute(
        "UPDATE tblCorrections SET status = 'Responded', comments = ?,"
        " responded_at = datetime('now') WHERE correction_id = ?",
        (comments, correction_id),
    )
    db.execute(
        "INSERT INTO tblCorrectionHistory(correction_id, action, actor_id, comments,"
        " action_at) VALUES (?, 'Responded', ?, ?, datetime('now'))",
        (correction_id, user["user_id"], comments),
    )
    set_status(row["application_id"], "Under Verification", None, user=user,
               module="Correction Management")
    number = db.scalar("SELECT application_number FROM tblApplications"
                       " WHERE application_id = ?", (row["application_id"],), default="")
    notify.send(row["raised_by"], "Correction Assigned",
                f"{number}: the operator has responded and sent it back for re-verification.",
                row["application_id"], kind="Action")


def close_correction(correction_id: int, closure_remarks: str, user: dict) -> None:
    db.execute(
        "UPDATE tblCorrections SET status = 'Closed', closure_remarks = ?,"
        " closed_at = datetime('now') WHERE correction_id = ?",
        (closure_remarks, correction_id),
    )
    db.execute(
        "INSERT INTO tblCorrectionHistory(correction_id, action, actor_id, comments,"
        " action_at) VALUES (?, 'Closed', ?, ?, datetime('now'))",
        (correction_id, user["user_id"], closure_remarks),
    )
    audit.log("Correction closed", "Correction Management", "tblCorrections",
              correction_id, new_value="Closed", user=user)


def decide(application_id: int, level: str, action: str, remarks: str,
           user: dict) -> str:
    """Record an approval decision and return the resulting status."""
    decision = {"Approve": "Approved", "Reject": "Rejected",
                "Send Back": "Sent Back", "Hold": "Hold",
                "Escalate": "Escalated"}[action]
    db.execute(
        "UPDATE tblApproval SET approver_id = ?, decision = ?, remarks = ?,"
        " approval_date = datetime('now')"
        " WHERE application_id = ? AND current_level = ? AND decision = 'Pending'",
        (user["user_id"], decision, remarks or None, application_id, level),
    )
    db.execute(
        "INSERT INTO tblApprovalHistory(application_id, level, approver_id, decision,"
        " remarks, action_at) VALUES (?,?,?,?,?, datetime('now'))",
        (application_id, level, user["user_id"], decision, remarks or None),
    )
    number = db.scalar("SELECT application_number FROM tblApplications"
                       " WHERE application_id = ?", (application_id,), default="")
    audit.log(f"{decision} at {level}", "Approval Workflow", "tblApplications",
              number, new_value=decision, user=user)
    owner = db.scalar("SELECT created_by FROM tblApplications"
                      " WHERE application_id = ?", (application_id,), default=None)

    if action == "Approve":
        nxt = next_level(level)
        if nxt:
            set_status(application_id, "Under Verification", nxt, user=user,
                       module="Approval Workflow")
            db.execute("INSERT INTO tblApproval(application_id, current_level, decision)"
                       " VALUES (?,?, 'Pending')", (application_id, nxt))
            return "Under Verification"
        set_status(application_id, "Approved", "Completed", user=user,
                   module="Approval Workflow")
        db.execute("UPDATE tblApplications SET approved_at = datetime('now')"
                   " WHERE application_id = ?", (application_id,))
        notify.send(owner, "Approval Completed",
                    f"{number}: approved at State Approval level.", application_id,
                    kind="Success")
        return "Approved"

    if action == "Reject":
        set_status(application_id, "Rejected", level, remarks, user=user,
                   module="Approval Workflow")
        notify.send(owner, "Application Rejected",
                    f"{number}: rejected at {level} — {remarks or 'no remark recorded'}",
                    application_id, kind="Alert")
        return "Rejected"

    if action == "Send Back":
        raise_correction(application_id,
                         reason=remarks or f"Sent back at {level}",
                         comments=f"Sent back at {level} for correction.",
                         raised_by=user["user_id"], user=user)
        return "Correction Required"

    if action == "Escalate":
        nxt = next_level(level) or "State Approval"
        set_status(application_id, "Under Verification", nxt, remarks, user=user,
                   module="Approval Workflow")
        db.execute("INSERT INTO tblApproval(application_id, current_level, decision)"
                   " VALUES (?,?, 'Pending')", (application_id, nxt))
        return "Under Verification"

    # Hold: the record stays where it is, with the reason on it.
    set_status(application_id, "Under Verification", level, remarks, user=user,
               module="Approval Workflow")
    db.execute("INSERT INTO tblApproval(application_id, current_level, decision)"
               " VALUES (?,?, 'Pending')", (application_id, level))
    return "Under Verification"


def lock(application_id: int, user: dict) -> None:
    db.execute(
        "INSERT INTO tblLockUnlock(application_id, lock_date, locked_by)"
        " VALUES (?, datetime('now'), ?)", (application_id, user["user_id"]))
    set_status(application_id, "Locked", "Completed", user=user, module="Lock / Unlock")
    number = db.scalar("SELECT application_number FROM tblApplications"
                       " WHERE application_id = ?", (application_id,), default="")
    owner = db.scalar("SELECT created_by FROM tblApplications"
                      " WHERE application_id = ?", (application_id,), default=None)
    notify.send(owner, "Lock Applied", f"{number}: locked; it can no longer be edited.",
                application_id)


def request_unlock(application_id: int, reason: str, user: dict) -> None:
    db.execute(
        "UPDATE tblLockUnlock SET unlock_reason = ?, unlock_requested_by = ?,"
        " unlock_requested_at = datetime('now'), unlock_status = 'Requested'"
        " WHERE lock_id = (SELECT MAX(lock_id) FROM tblLockUnlock WHERE application_id = ?)",
        (reason, user["user_id"], application_id),
    )
    number = db.scalar("SELECT application_number FROM tblApplications"
                       " WHERE application_id = ?", (application_id,), default="")
    audit.log("Unlock requested", "Lock / Unlock", "tblApplications", number,
              new_value=reason, user=user)
    for uid in db.query(
        "SELECT u.user_id FROM tblUsers u JOIN tblUserRoles ur ON ur.user_id = u.user_id"
        " JOIN tblRoles r ON r.role_id = ur.role_id WHERE r.role_name = 'State Admin'"
    ):
        notify.send(uid["user_id"], "Correction Raised",
                    f"{number}: unlock requested — {reason}", application_id,
                    kind="Action")


def decide_unlock(lock_id: int, approve: bool, user: dict) -> None:
    row = db.one("SELECT application_id, unlock_requested_by FROM tblLockUnlock"
                 " WHERE lock_id = ?", (lock_id,))
    db.execute(
        "UPDATE tblLockUnlock SET unlock_status = ?, unlock_approved_by = ?,"
        " unlock_date = CASE WHEN ? THEN datetime('now') ELSE NULL END"
        " WHERE lock_id = ?",
        ("Approved" if approve else "Rejected", user["user_id"], 1 if approve else 0,
         lock_id),
    )
    number = db.scalar("SELECT application_number FROM tblApplications"
                       " WHERE application_id = ?", (row["application_id"],), default="")
    if approve:
        set_status(row["application_id"], "Approved", "Completed", user=user,
                   module="Lock / Unlock")
        notify.send(row["unlock_requested_by"], "Unlock Approved",
                    f"{number}: unlocked for editing. Re-lock it once the edit is done.",
                    row["application_id"], kind="Success")
    else:
        notify.send(row["unlock_requested_by"], "Unlock Approved",
                    f"{number}: the unlock request was rejected.",
                    row["application_id"], kind="Alert")
    audit.log("Unlock " + ("approved" if approve else "rejected"), "Lock / Unlock",
              "tblLockUnlock", lock_id, new_value="Approved" if approve else "Rejected",
              user=user)


def relock(lock_id: int, user: dict) -> None:
    row = db.one("SELECT application_id FROM tblLockUnlock WHERE lock_id = ?", (lock_id,))
    db.execute("UPDATE tblLockUnlock SET unlock_status = 'Relocked',"
               " relock_date = datetime('now') WHERE lock_id = ?", (lock_id,))
    set_status(row["application_id"], "Locked", "Completed", user=user,
               module="Lock / Unlock")
