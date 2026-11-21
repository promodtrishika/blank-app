"""Screen 07 — Application Details (blueprint module 3)."""

from __future__ import annotations

import streamlit as st

from app import auth, db, theme, ui

user = auth.require("app.view")

ui.page_header("Application Details",
               "One record, with its verification, corrections, approvals and locks.",
               ":material/description:")

filters = ui.filter_row(key="detail", statuses=theme.APP_STATUSES,
                        with_dates=False)
where, params = ui.where_from_filters(filters)
frame = ui.applications(where, params, limit=400)

if frame.empty:
    ui.empty_state("No application matches these filters.")
    st.stop()

row = ui.pick_application(frame, key="detail_pick")
if row is None:
    st.stop()
app_id = int(row["application_id"])

head = st.columns([3, 1])
with head[0]:
    st.subheader(f"{row['application_number']} — {row['applicant_name']}",
                 anchor=False, divider="gray")
with head[1]:
    ui.badge(row["status"])
    if row["is_locked"]:
        st.caption("Locked records cannot be edited until an unlock is approved.")

ui.detail_grid(row, [
    ("Service", "service_name"),
    ("Department", "department_name"),
    ("District", "district_name"),
    ("Sub-division", "subdivision"),
    ("Block", "block_name"),
    ("Office", "office_name"),
    ("Submitted", "submission_date"),
    ("Current level", "current_level"),
    ("QAP score", "score"),
    ("Age (days)", "age_days"),
    ("Approved at", "approved_at"),
    ("Remarks", "remarks"),
])

extra = db.frame(
    "SELECT field_name, field_value FROM tblApplicationDetails"
    " WHERE application_id = ? ORDER BY detail_id", [app_id])
if not extra.empty:
    ui.section("Recorded fields")
    ui.table(extra, columns={
        "field_name": st.column_config.TextColumn("Field", width="medium"),
        "field_value": st.column_config.TextColumn("Value", width="large"),
    })

ui.section("Verification")
ver = db.frame(
    "SELECT v.verification_id, v.score, v.result, v.quality_assessment,"
    " v.recommendation, v.remarks, v.verified_at, u.employee_name AS verifier"
    "  FROM tblVerification v LEFT JOIN tblUsers u ON u.user_id = v.verifier_id"
    " WHERE v.application_id = ? ORDER BY v.verified_at DESC", [app_id])
if ver.empty:
    ui.empty_state("Not verified yet.", ":material/fact_check:")
else:
    latest = ver.iloc[0]
    cols = st.columns(4)
    with cols[0]:
        st.metric("Score", f"{latest['score']:.0f}/100", border=True)
    with cols[1]:
        st.caption("Result")
        ui.badge(latest["result"], theme.VERIFICATION_BADGE)
    with cols[2]:
        st.metric("Quality", latest["quality_assessment"] or "—", border=True)
    with cols[3]:
        st.metric("Verifier", latest["verifier"] or "—", border=True)
    st.caption(f"Recommendation: {latest['recommendation'] or '—'}")
    items = db.frame(
        "SELECT item_code, item_text, weight, result, comment"
        "  FROM tblVerificationChecklist WHERE verification_id = ?"
        " ORDER BY item_code", [int(latest["verification_id"])])
    ui.table(items, columns={
        "item_code": st.column_config.TextColumn("Item"),
        "item_text": st.column_config.TextColumn("Checklist item", width="large"),
        "weight": st.column_config.NumberColumn("Weight", format="%d"),
        "result": st.column_config.TextColumn("Result"),
        "comment": st.column_config.TextColumn("Comment", width="medium"),
    })
    if len(ver) > 1:
        with st.expander(f"Earlier verification rounds ({len(ver) - 1})"):
            ui.table(ver.iloc[1:], columns={})

ui.section("Corrections")
cor = db.frame(
    "SELECT c.correction_id, c.reason, c.status, c.comments,"
    " r.employee_name AS raised_by, t.employee_name AS assigned_to,"
    " c.raised_at, c.responded_at, c.closed_at"
    "  FROM tblCorrections c"
    "  LEFT JOIN tblUsers r ON r.user_id = c.raised_by"
    "  LEFT JOIN tblUsers t ON t.user_id = c.assigned_to"
    " WHERE c.application_id = ? ORDER BY c.raised_at DESC", [app_id])
if cor.empty:
    ui.empty_state("No correction has been raised.", ":material/build:")
else:
    ui.table(cor.drop(columns=["correction_id"]), columns={
        "reason": st.column_config.TextColumn("Reason", width="large"),
        "status": st.column_config.TextColumn("Status"),
        "comments": st.column_config.TextColumn("Comments", width="medium"),
        "raised_by": st.column_config.TextColumn("Raised by"),
        "assigned_to": st.column_config.TextColumn("Assigned to"),
        "raised_at": st.column_config.TextColumn("Raised"),
        "responded_at": st.column_config.TextColumn("Responded"),
        "closed_at": st.column_config.TextColumn("Closed"),
    })

ui.section("Approval history")
app_hist = db.frame(
    "SELECT h.level, h.decision, h.remarks, u.employee_name AS approver,"
    " h.action_at FROM tblApprovalHistory h"
    "  LEFT JOIN tblUsers u ON u.user_id = h.approver_id"
    " WHERE h.application_id = ? ORDER BY h.action_at", [app_id])
if app_hist.empty:
    ui.empty_state("The record has not entered the approval chain.",
                   ":material/approval:")
else:
    ui.table(app_hist, columns={
        "level": st.column_config.TextColumn("Level", width="medium"),
        "decision": st.column_config.TextColumn("Decision"),
        "remarks": st.column_config.TextColumn("Remarks", width="large"),
        "approver": st.column_config.TextColumn("By"),
        "action_at": st.column_config.TextColumn("When"),
    })
pending = db.one(
    "SELECT current_level FROM tblApproval WHERE application_id = ?"
    " AND decision = 'Pending' ORDER BY approval_id DESC LIMIT 1", [app_id])
if pending:
    st.markdown(f"**Waiting at** :blue-badge[:material/schedule: "
                f"{pending['current_level']}]")

ui.section("Lock and unlock")
lock = db.frame(
    "SELECT l.lock_date, lb.employee_name AS locked_by, l.unlock_reason,"
    " rb.employee_name AS unlock_requested_by, l.unlock_requested_at,"
    " l.unlock_status, ab.employee_name AS unlock_approved_by, l.unlock_date,"
    " l.relock_date FROM tblLockUnlock l"
    "  LEFT JOIN tblUsers lb ON lb.user_id = l.locked_by"
    "  LEFT JOIN tblUsers rb ON rb.user_id = l.unlock_requested_by"
    "  LEFT JOIN tblUsers ab ON ab.user_id = l.unlock_approved_by"
    " WHERE l.application_id = ? ORDER BY l.lock_id DESC", [app_id])
if lock.empty:
    ui.empty_state("Never locked.", ":material/lock_open:")
else:
    ui.table(lock, columns={})

ui.section("Documents")
docs = db.frame(
    "SELECT d.file_name, d.file_type, d.file_size, d.version,"
    " u.employee_name AS uploaded_by, d.upload_time,"
    " CASE d.verified WHEN 1 THEN 'Verified' ELSE 'Not verified' END AS attachment"
    "  FROM tblDocuments d LEFT JOIN tblUsers u ON u.user_id = d.uploaded_by"
    " WHERE d.application_id = ? ORDER BY d.upload_time", [app_id])
if docs.empty:
    ui.empty_state("No document attached.", ":material/folder_off:")
else:
    ui.table(docs, columns={
        "file_name": st.column_config.TextColumn("File", width="medium"),
        "file_type": st.column_config.TextColumn("Type"),
        "file_size": st.column_config.NumberColumn("Size (bytes)", format="%d"),
        "version": st.column_config.NumberColumn("Version", format="%d"),
        "uploaded_by": st.column_config.TextColumn("Uploaded by"),
        "upload_time": st.column_config.TextColumn("When"),
        "attachment": st.column_config.TextColumn("Attachment check"),
    })

ui.section("Audit trail for this application")
trail = db.frame(
    "SELECT activity, module, username, old_value, new_value, ip_address,"
    " browser, timestamp FROM tblAuditLogs WHERE entity_id = ?"
    " ORDER BY timestamp DESC LIMIT 100", [row["application_number"]])
if trail.empty:
    ui.empty_state("Nothing recorded against this application yet.",
                   ":material/history:")
else:
    ui.table(trail, columns={
        "activity": st.column_config.TextColumn("Activity", width="medium"),
        "module": st.column_config.TextColumn("Module", width="medium"),
        "username": st.column_config.TextColumn("By"),
        "old_value": st.column_config.TextColumn("From"),
        "new_value": st.column_config.TextColumn("To"),
        "ip_address": st.column_config.TextColumn("IP"),
        "browser": st.column_config.TextColumn("Browser"),
        "timestamp": st.column_config.TextColumn("When"),
    })
