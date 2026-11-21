"""Screen 09 — Corrections (blueprint module 5)."""

from __future__ import annotations

import streamlit as st

from app import auth, db, theme, ui, workflow

user = auth.require("correction.raise", "correction.respond", "correction.assign")

ui.page_header("Corrections",
               "Raise, assign, answer and close corrections; each answer goes back "
               "for re-verification.",
               ":material/build:")

scope, scope_params = auth.scope_clause()

CORRECTION_SQL = f"""
SELECT c.correction_id, a.application_id, a.application_number, a.applicant_name,
       s.service_name, d.district_name, c.reason, c.comments, c.status,
       r.employee_name AS raised_by, t.employee_name AS assigned_to,
       c.assigned_to AS assigned_to_id, c.raised_at, c.responded_at,
       c.closed_at, c.closure_remarks,
       CAST(julianday('now') - julianday(c.raised_at) AS INTEGER) AS age_days
  FROM tblCorrections c
  JOIN tblApplications a   ON a.application_id = c.application_id
  JOIN tblServiceMaster s  ON s.service_id = a.service_id
  JOIN tblDistrictMaster d ON d.district_id = a.district_id
  LEFT JOIN tblUsers r ON r.user_id = c.raised_by
  LEFT JOIN tblUsers t ON t.user_id = c.assigned_to
 WHERE {scope}
"""
COLUMNS = {
    "application_number": st.column_config.TextColumn("Application", width="medium"),
    "applicant_name": st.column_config.TextColumn("Applicant"),
    "service_name": st.column_config.TextColumn("Service"),
    "district_name": st.column_config.TextColumn("District"),
    "reason": st.column_config.TextColumn("Reason", width="large"),
    "status": st.column_config.TextColumn("Status"),
    "raised_by": st.column_config.TextColumn("Raised by"),
    "assigned_to": st.column_config.TextColumn("Assigned to"),
    "raised_at": st.column_config.TextColumn("Raised"),
    "age_days": st.column_config.NumberColumn("Age (days)", format="%d"),
}
VIEW = ["application_number", "applicant_name", "service_name", "district_name",
        "reason", "status", "raised_by", "assigned_to", "raised_at", "age_days"]

everything = db.frame(CORRECTION_SQL + " ORDER BY c.raised_at DESC", scope_params)
open_ = everything[everything["status"] != "Closed"] if not everything.empty else everything

ui.kpi_row([
    ("Open", f"{int((everything['status'] == 'Open').sum()) if not everything.empty else 0:,}"),
    ("Assigned", f"{int((everything['status'] == 'Assigned').sum()) if not everything.empty else 0:,}"),
    ("Responded", f"{int((everything['status'] == 'Responded').sum()) if not everything.empty else 0:,}"),
    ("Closed", f"{int((everything['status'] == 'Closed').sum()) if not everything.empty else 0:,}"),
])

tab_names = []
if auth.has("correction.respond"):
    tab_names.append("Assigned to me")
tab_names += ["Open corrections"]
if auth.has("correction.raise"):
    tab_names.append("Raise a correction")
if auth.has("correction.raise", "correction.assign"):
    tab_names.append("Close a correction")
tab_names.append("History")
tabs = dict(zip(tab_names, st.tabs(tab_names)))

if "Assigned to me" in tabs:
    with tabs["Assigned to me"]:
        mine = (open_[(open_["assigned_to_id"] == user["user_id"])
                      & (open_["status"].isin(["Open", "Assigned"]))]
                if not open_.empty else open_)
        if mine.empty:
            ui.empty_state("Nothing is waiting on you.", ":material/task_alt:")
        else:
            ui.table(mine[VIEW], columns=COLUMNS, height=240)
            choice = st.selectbox(
                "Correction to answer", mine["correction_id"].tolist(),
                format_func=lambda cid: (
                    f"{mine.loc[mine.correction_id == cid, 'application_number'].iloc[0]}"
                    f" — {mine.loc[mine.correction_id == cid, 'reason'].iloc[0]}"),
                key="respond_pick")
            with st.form("respond", border=True):
                answer = st.text_area("What you corrected *", height=100)
                send = st.form_submit_button(
                    "Respond and resubmit", type="primary", icon=":material/reply:",
                    width="stretch")
            if send:
                if not answer.strip():
                    st.error("Say what you corrected before resubmitting.",
                             icon=":material/error:")
                else:
                    workflow.respond_correction(int(choice), answer.strip(), user)
                    st.success("Answered. The record is back in the verification "
                               "queue.", icon=":material/reply:")
                    st.rerun()

with tabs["Open corrections"]:
    if open_.empty:
        ui.empty_state("No open correction in your scope.", ":material/task_alt:")
    else:
        ui.table(open_[VIEW], columns=COLUMNS, height=360)
        ui.download_row(open_[VIEW], "open-corrections")

if "Raise a correction" in tabs:
    with tabs["Raise a correction"]:
        eligible = ui.applications(
            f"{scope} AND a.status IN ('Submitted', 'Under Verification')",
            scope_params)
        if eligible.empty:
            ui.empty_state("No submitted or in-verification record to raise "
                           "a correction against.")
        else:
            row = ui.pick_application(eligible, key="raise_pick")
            operators = db.query(
                "SELECT u.user_id, u.employee_name FROM tblUsers u"
                " JOIN tblUserRoles ur ON ur.user_id = u.user_id"
                " JOIN tblRoles r ON r.role_id = ur.role_id"
                " WHERE r.role_name = 'Operator' AND u.status = 'Active'"
                " AND u.district_id = (SELECT district_id FROM tblApplications"
                " WHERE application_id = ?) ORDER BY u.employee_name",
                (int(row["application_id"]),)) if row else []
            with st.form("raise", border=True):
                reason = st.text_input("Reason *",
                                       placeholder="What is wrong with the record")
                comments = st.text_area("Instructions for the operator", height=80)
                assignee = st.selectbox(
                    "Assign to",
                    [o["user_id"] for o in operators] or [None],
                    format_func=lambda uid: next(
                        (o["employee_name"] for o in operators if o["user_id"] == uid),
                        "The operator who filed it"),
                    disabled=not auth.has("correction.assign") or not operators,
                    help="Without the assign permission it goes to the operator "
                         "who filed the record.")
                raise_it = st.form_submit_button(
                    "Raise correction", type="primary", icon=":material/report:",
                    width="stretch")
            if raise_it and row:
                if not reason.strip():
                    st.error("A correction needs a reason.", icon=":material/error:")
                else:
                    workflow.raise_correction(
                        int(row["application_id"]), reason.strip(),
                        comments.strip(), user["user_id"], user,
                        assigned_to=assignee if auth.has("correction.assign") else None)
                    st.success(f"Correction raised on {row['application_number']}.",
                               icon=":material/report:")
                    st.rerun()

if "Close a correction" in tabs:
    with tabs["Close a correction"]:
        closable = (open_[open_["status"] == "Responded"]
                    if not open_.empty else open_)
        if closable.empty:
            ui.empty_state("No answered correction is waiting to be closed.",
                           ":material/task_alt:")
        else:
            ui.table(closable[VIEW], columns=COLUMNS, height=220)
            cid = st.selectbox(
                "Correction to close", closable["correction_id"].tolist(),
                format_func=lambda c: closable.loc[
                    closable.correction_id == c, "application_number"].iloc[0],
                key="close_pick")
            with st.form("close", border=True):
                remark = st.text_area("Closure remarks *", height=80)
                close_it = st.form_submit_button(
                    "Close correction", type="primary", icon=":material/task_alt:",
                    width="stretch")
            if close_it:
                if not remark.strip():
                    st.error("Closure needs a remark.", icon=":material/error:")
                else:
                    workflow.close_correction(int(cid), remark.strip(), user)
                    st.success("Correction closed.", icon=":material/task_alt:")
                    st.rerun()

with tabs["History"]:
    hist = db.frame(
        "SELECT a.application_number, h.action, u.employee_name AS actor,"
        " h.comments, h.action_at FROM tblCorrectionHistory h"
        " JOIN tblCorrections c ON c.correction_id = h.correction_id"
        " JOIN tblApplications a ON a.application_id = c.application_id"
        " LEFT JOIN tblUsers u ON u.user_id = h.actor_id"
        f" WHERE {scope} ORDER BY h.action_at DESC LIMIT 300", scope_params)
    if hist.empty:
        ui.empty_state("No correction history in your scope.", ":material/history:")
    else:
        ui.table(hist, columns={
            "application_number": st.column_config.TextColumn("Application"),
            "action": st.column_config.TextColumn("Action"),
            "actor": st.column_config.TextColumn("By"),
            "comments": st.column_config.TextColumn("Comments", width="large"),
            "action_at": st.column_config.TextColumn("When"),
        })
