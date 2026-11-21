"""Screen 11 — Lock / Unlock (blueprint module 7).

Approved record → Lock → Unlock request → Approval → Unlock → Edit → Relock.
"""

from __future__ import annotations

import streamlit as st

from app import auth, db, theme, ui, workflow

user = auth.require("lock.apply", "unlock.request", "unlock.approve")

ui.page_header("Lock / Unlock",
               "Approved → Lock → Unlock request → Approval → Unlock → Edit → Relock.",
               ":material/lock:")

scope, scope_params = auth.scope_clause()

LOCK_BASE = f"""
SELECT l.lock_id, a.application_id, a.application_number, a.applicant_name,
       s.service_name, d.district_name, a.status, l.lock_date,
       lb.employee_name AS locked_by, l.unlock_reason, l.unlock_status,
       rb.employee_name AS unlock_requested_by, l.unlock_requested_at,
       ab.employee_name AS unlock_approved_by, l.unlock_date, l.relock_date
  FROM tblLockUnlock l
  JOIN tblApplications a   ON a.application_id = l.application_id
  JOIN tblServiceMaster s  ON s.service_id = a.service_id
  JOIN tblDistrictMaster d ON d.district_id = a.district_id
  LEFT JOIN tblUsers lb ON lb.user_id = l.locked_by
  LEFT JOIN tblUsers rb ON rb.user_id = l.unlock_requested_by
  LEFT JOIN tblUsers ab ON ab.user_id = l.unlock_approved_by
 WHERE {scope}
"""
# The newest lock row per application is its current lock state.
LOCK_SQL = LOCK_BASE + """
   AND l.lock_id = (SELECT MAX(x.lock_id) FROM tblLockUnlock x
                     WHERE x.application_id = l.application_id)
"""
COLUMNS = {
    "application_number": st.column_config.TextColumn("Application", width="medium"),
    "applicant_name": st.column_config.TextColumn("Applicant"),
    "service_name": st.column_config.TextColumn("Service"),
    "district_name": st.column_config.TextColumn("District"),
    "status": st.column_config.TextColumn("Status"),
    "lock_date": st.column_config.TextColumn("Locked"),
    "locked_by": st.column_config.TextColumn("Locked by"),
    "unlock_reason": st.column_config.TextColumn("Unlock reason", width="large"),
    "unlock_status": st.column_config.TextColumn("Unlock status"),
    "unlock_requested_by": st.column_config.TextColumn("Requested by"),
    "unlock_requested_at": st.column_config.TextColumn("Requested"),
    "unlock_approved_by": st.column_config.TextColumn("Decided by"),
    "unlock_date": st.column_config.TextColumn("Unlocked"),
    "relock_date": st.column_config.TextColumn("Relocked"),
}

latest = db.frame(LOCK_SQL + " ORDER BY l.lock_date DESC", scope_params)
approved_unlocked = ui.applications(
    f"{scope} AND a.status = 'Approved'", scope_params, order="a.approved_at DESC")


def n(mask) -> int:
    return int(mask.sum()) if not latest.empty else 0


ui.kpi_row([
    ("Locked", f"{n(latest['status'] == 'Locked') if not latest.empty else 0:,}"),
    ("Ready to lock", f"{len(approved_unlocked):,}",
     "Approved and not locked — including records unlocked for an edit."),
    ("Unlock requests waiting",
     f"{n(latest['unlock_status'] == 'Requested') if not latest.empty else 0:,}"),
    ("Unlocked for editing",
     f"{n(latest['unlock_status'] == 'Approved') if not latest.empty else 0:,}"),
])

names = []
if auth.has("lock.apply"):
    names += ["Lock approved records"]
if auth.has("unlock.request"):
    names += ["Request an unlock"]
if auth.has("unlock.approve"):
    names += ["Decide unlock requests"]
if auth.has("lock.apply"):
    names += ["Relock after edit"]
names += ["Lock history", "Unlock history"]
tabs = dict(zip(names, st.tabs(names)))

if "Lock approved records" in tabs:
    with tabs["Lock approved records"]:
        if approved_unlocked.empty:
            ui.empty_state("Every approved record in your scope is locked.",
                           ":material/lock:")
        else:
            ui.table(approved_unlocked[["application_number", "applicant_name",
                                        "service_name", "district_name",
                                        "approved_at"]], height=240)
            picked = st.multiselect(
                "Records to lock", approved_unlocked["application_id"].tolist(),
                format_func=lambda i: approved_unlocked.loc[
                    approved_unlocked.application_id == i,
                    "application_number"].iloc[0],
                placeholder="Choose one or more")
            if st.button("Lock selected", type="primary", icon=":material/lock:",
                         disabled=not picked):
                for aid in picked:
                    workflow.lock(int(aid), user)
                st.success(f"{len(picked)} record(s) locked.", icon=":material/lock:")
                st.rerun()

if "Request an unlock" in tabs:
    with tabs["Request an unlock"]:
        lockable = (latest[(latest["status"] == "Locked")
                           & (latest["unlock_status"].isna()
                              | latest["unlock_status"].isin(["Rejected", "Relocked"]))]
                    if not latest.empty else latest)
        if lockable.empty:
            ui.empty_state("No locked record is free for an unlock request.",
                           ":material/lock_open:")
        else:
            aid = st.selectbox(
                "Locked record", lockable["application_id"].tolist(),
                format_func=lambda i: (
                    f"{lockable.loc[lockable.application_id == i, 'application_number'].iloc[0]}"
                    f" — {lockable.loc[lockable.application_id == i, 'applicant_name'].iloc[0]}"),
                key="unlock_req_pick")
            with st.form("unlock_request", border=True):
                reason = st.text_area("Reason for unlocking *", height=90)
                ask = st.form_submit_button("Request unlock", type="primary",
                                            icon=":material/key:", width="stretch")
            if ask:
                if not reason.strip():
                    st.error("An unlock request needs a reason.",
                             icon=":material/error:")
                else:
                    workflow.request_unlock(int(aid), reason.strip(), user)
                    st.success("Unlock requested. The State Admin has been notified.",
                               icon=":material/key:")
                    st.rerun()

if "Decide unlock requests" in tabs:
    with tabs["Decide unlock requests"]:
        waiting = (latest[latest["unlock_status"] == "Requested"]
                   if not latest.empty else latest)
        if waiting.empty:
            ui.empty_state("No unlock request is waiting.", ":material/task_alt:")
        else:
            ui.table(waiting[["application_number", "applicant_name",
                              "district_name", "unlock_reason",
                              "unlock_requested_by", "unlock_requested_at"]],
                     columns=COLUMNS, height=220)
            lid = st.selectbox(
                "Request", waiting["lock_id"].tolist(),
                format_func=lambda i: waiting.loc[
                    waiting.lock_id == i, "application_number"].iloc[0],
                key="unlock_decide_pick")
            cols = st.columns(2)
            with cols[0]:
                if st.button("Approve unlock", type="primary",
                             icon=":material/lock_open:", width="stretch"):
                    workflow.decide_unlock(int(lid), True, user)
                    st.success("Unlocked. The record is editable until relocked.",
                               icon=":material/lock_open:")
                    st.rerun()
            with cols[1]:
                if st.button("Reject unlock", icon=":material/cancel:",
                             width="stretch"):
                    workflow.decide_unlock(int(lid), False, user)
                    st.success("Unlock request rejected; the record stays locked.",
                               icon=":material/cancel:")
                    st.rerun()

if "Relock after edit" in tabs:
    with tabs["Relock after edit"]:
        editable = (latest[(latest["unlock_status"] == "Approved")
                           & (latest["status"] == "Approved")]
                    if not latest.empty else latest)
        if editable.empty:
            ui.empty_state("No record is unlocked for editing.", ":material/lock:")
        else:
            ui.table(editable[["application_number", "applicant_name",
                               "district_name", "unlock_reason", "unlock_date"]],
                     columns=COLUMNS, height=200)
            lid = st.selectbox(
                "Record to relock", editable["lock_id"].tolist(),
                format_func=lambda i: editable.loc[
                    editable.lock_id == i, "application_number"].iloc[0],
                key="relock_pick")
            if st.button("Relock", type="primary", icon=":material/lock:"):
                workflow.relock(int(lid), user)
                st.success("Relocked.", icon=":material/lock:")
                st.rerun()

with tabs["Lock history"]:
    hist = db.frame(LOCK_BASE + " ORDER BY l.lock_date DESC LIMIT 400",
                    scope_params)
    if hist.empty:
        ui.empty_state("Nothing has been locked in your scope.", ":material/lock:")
    else:
        view = hist[["application_number", "applicant_name", "district_name",
                     "lock_date", "locked_by", "relock_date"]]
        ui.table(view, columns=COLUMNS)
        ui.download_row(view, "lock-history")

with tabs["Unlock history"]:
    unl = (latest[latest["unlock_status"].notna()] if not latest.empty else latest)
    if unl.empty:
        ui.empty_state("No unlock has been requested in your scope.",
                       ":material/lock_open:")
    else:
        view = unl[["application_number", "applicant_name", "district_name",
                    "unlock_reason", "unlock_status", "unlock_requested_by",
                    "unlock_requested_at", "unlock_approved_by", "unlock_date"]]
        ui.table(view, columns=COLUMNS)
        ui.download_row(view, "unlock-history")
