"""Screen 10 — Approvals (blueprint module 6)."""

from __future__ import annotations

import streamlit as st

from app import auth, charts, db, theme, ui, workflow

user = auth.require(*workflow.LEVEL_PERMISSION.values())

ui.page_header("Approvals",
               "Operator → District Reviewer → District Approver → State Reviewer → "
               "State Approval.",
               ":material/approval:")

my_levels = [lvl for lvl, perm in workflow.LEVEL_PERMISSION.items() if auth.has(perm)]
scope, scope_params = auth.scope_clause()

counts = {r["current_level"]: r["n"] for r in db.query(
    "SELECT a.current_level, COUNT(*) AS n FROM tblApplications a"
    f" WHERE {scope} AND a.status = 'Under Verification'"
    " AND a.current_level IS NOT NULL GROUP BY a.current_level", scope_params)}

ui.kpi_row([(f"At {lvl}", f"{counts.get(lvl, 0):,}",
             "You act at this level." if lvl in my_levels else None)
            for lvl in workflow.LEVELS])

st.markdown("**You act at:** " + " ".join(
    f":blue-badge[:material/how_to_reg: {lvl}]" for lvl in my_levels))

level = st.segmented_control("Level", my_levels, default=my_levels[0],
                             key="approval_level")
if not level:
    st.stop()

queue = ui.applications(
    f"{scope} AND a.status = 'Under Verification' AND a.current_level = ?",
    scope_params + [level], order="a.submitted_at ASC")

ui.section(f"Waiting at {level}")
if queue.empty:
    ui.empty_state(f"Nothing is waiting at {level} in your scope.",
                   ":material/task_alt:")
else:
    ui.table(queue[["application_number", "applicant_name", "service_name",
                    "district_name", "score", "submission_date", "age_days"]],
             height=260)

    row = ui.pick_application(queue, key="approve_pick")
    if row:
        app_id = int(row["application_id"])
        ui.detail_grid(row, [("Service", "service_name"),
                             ("District", "district_name"),
                             ("QAP score", "score"),
                             ("Submitted", "submission_date"),
                             ("Age (days)", "age_days"),
                             ("Remarks", "remarks")])
        trail = db.frame(
            "SELECT h.level, h.decision, u.employee_name AS approver, h.remarks,"
            " h.action_at FROM tblApprovalHistory h"
            " LEFT JOIN tblUsers u ON u.user_id = h.approver_id"
            " WHERE h.application_id = ? ORDER BY h.action_at", [app_id])
        if not trail.empty:
            with st.expander(f"Decisions so far ({len(trail)})"):
                ui.table(trail, columns={})

        with st.form("decision", border=True):
            st.subheader("Decision", anchor=False)
            action = st.radio("Action", workflow.APPROVAL_ACTIONS, horizontal=True,
                              help="Approve moves it to the next level; Send Back "
                                   "raises a correction; Hold keeps it here; "
                                   "Escalate skips to the next level.")
            remarks = st.text_area("Remarks", height=80,
                                   placeholder="Required for anything but Approve.")
            go = st.form_submit_button("Record decision", type="primary",
                                       icon=":material/gavel:", width="stretch")
        if go:
            if action != "Approve" and not remarks.strip():
                st.error(f"{action} needs a remark.", icon=":material/error:")
            else:
                outcome = workflow.decide(app_id, level, action, remarks.strip(), user)
                st.success(f"{row['application_number']}: {action.lower()} recorded "
                           f"at {level}. It is now {outcome}.",
                           icon=":material/gavel:")
                st.rerun()

ui.section("Approval trend", "Decisions recorded per month, in your scope.")
trend = db.frame(
    "SELECT strftime('%Y-%m', h.action_at) AS month,"
    " CASE WHEN h.decision = 'Approved' THEN 'Approved'"
    "      WHEN h.decision = 'Rejected' THEN 'Rejected'"
    "      ELSE 'Sent back or held' END AS series,"
    " COUNT(*) AS decisions"
    "  FROM tblApprovalHistory h"
    "  JOIN tblApplications a ON a.application_id = h.application_id"
    f" WHERE {scope} GROUP BY month, series ORDER BY month", scope_params)
charts.trend(trend, x="month", y="decisions", series="series",
             order=["Approved", "Rejected", "Sent back or held"],
             x_title="Month", y_title="Decisions")
