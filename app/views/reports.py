"""Screen 12 — Reports (blueprint module 10)."""

from __future__ import annotations

import streamlit as st

from app import auth, db, ui

user = auth.require("report.view")

ui.page_header("Reports",
               "Nine standard reports, filtered the same way, exported as PDF, "
               "Excel or CSV.",
               ":material/summarize:")

REPORTS = [
    "Submission Report", "Verification Report", "Correction Report",
    "Approval Report", "Pending Report", "Lock Report", "Unlock Report",
    "User Activity Report", "Audit Report",
]
NEEDS_AUDIT = {"User Activity Report", "Audit Report"}
available = [r for r in REPORTS if r not in NEEDS_AUDIT or auth.has("audit.view")]

report = st.selectbox("Report", available, key="report_kind")

# Filter row — Date range, District, Division, Department, Service.
cols = st.columns([3, 2, 2, 2, 2])
with cols[0]:
    dates = st.date_input("Date range", value=(), key="rep_dates",
                          help="Leave empty for every date on record.")
districts = auth.districts_in_scope()
with cols[1]:
    pick_districts = st.multiselect("District", [d["district_name"] for d in districts],
                                    placeholder="Any district", key="rep_district")
with cols[2]:
    pick_divisions = st.multiselect(
        "Division", sorted({d["division_name"] for d in districts}),
        placeholder="Any division", key="rep_division")
with cols[3]:
    departments = [r["department_name"] for r in db.query(
        "SELECT department_name FROM tblDepartmentMaster ORDER BY department_name")]
    pick_departments = st.multiselect("Department", departments,
                                      placeholder="Any department", key="rep_dept")
with cols[4]:
    services = [r["service_name"] for r in db.query(
        "SELECT service_name FROM tblServiceMaster ORDER BY service_name")]
    pick_services = st.multiselect("Service", services, placeholder="Any service",
                                   key="rep_service")

scope, params = auth.scope_clause("a")
conds = [scope]


def add_in(column: str, values: list) -> None:
    if values:
        conds.append(f"{column} IN ({','.join('?' * len(values))})")
        params.extend(values)


add_in("d.district_name", pick_districts)
add_in("v.division_name", pick_divisions)
add_in("dep.department_name", pick_departments)
add_in("s.service_name", pick_services)


def date_cond(column: str) -> None:
    if isinstance(dates, (tuple, list)) and len(dates) == 2:
        conds.append(f"date({column}) BETWEEN ? AND ?")
        params.extend([str(dates[0]), str(dates[1])])


JOINS = """
  FROM tblApplications a
  JOIN tblServiceMaster s      ON s.service_id = a.service_id
  JOIN tblDepartmentMaster dep ON dep.department_id = a.department_id
  JOIN tblDistrictMaster d     ON d.district_id = a.district_id
  JOIN tblDivisionMaster v     ON v.division_id = d.division_id
"""

if report == "Submission Report":
    date_cond("a.submission_date")
    sql = ("SELECT a.application_number, a.applicant_name, s.service_name,"
           " dep.department_name, d.district_name, v.division_name, a.status,"
           " a.submission_date" + JOINS)
    order = " ORDER BY a.submission_date DESC"
elif report == "Verification Report":
    date_cond("vr.verified_at")
    sql = ("SELECT a.application_number, s.service_name, d.district_name,"
           " u.employee_name AS verifier, vr.score, vr.result,"
           " vr.quality_assessment, vr.recommendation, vr.verified_at" + JOINS
           + " JOIN tblVerification vr ON vr.application_id = a.application_id"
             " LEFT JOIN tblUsers u ON u.user_id = vr.verifier_id")
    order = " ORDER BY vr.verified_at DESC"
elif report == "Correction Report":
    date_cond("c.raised_at")
    sql = ("SELECT a.application_number, s.service_name, d.district_name,"
           " c.reason, c.status, r.employee_name AS raised_by,"
           " t.employee_name AS assigned_to, c.raised_at, c.responded_at,"
           " c.closed_at, c.closure_remarks" + JOINS
           + " JOIN tblCorrections c ON c.application_id = a.application_id"
             " LEFT JOIN tblUsers r ON r.user_id = c.raised_by"
             " LEFT JOIN tblUsers t ON t.user_id = c.assigned_to")
    order = " ORDER BY c.raised_at DESC"
elif report == "Approval Report":
    date_cond("h.action_at")
    sql = ("SELECT a.application_number, s.service_name, d.district_name, h.level,"
           " h.decision, u.employee_name AS approver, h.remarks, h.action_at" + JOINS
           + " JOIN tblApprovalHistory h ON h.application_id = a.application_id"
             " LEFT JOIN tblUsers u ON u.user_id = h.approver_id")
    order = " ORDER BY h.action_at DESC"
elif report == "Pending Report":
    date_cond("a.submission_date")
    conds.append("a.status IN ('Submitted','Under Verification','Correction Required')")
    sql = ("SELECT a.application_number, a.applicant_name, s.service_name,"
           " d.district_name, a.status, a.current_level, a.submission_date,"
           " s.sla_days,"
           " CAST(julianday('now') - julianday(a.submitted_at) AS INTEGER) AS age_days,"
           " CASE WHEN julianday('now') - julianday(a.submitted_at) > s.sla_days"
           "      THEN 'Beyond SLA' ELSE 'Within SLA' END AS sla_position" + JOINS)
    order = " ORDER BY age_days DESC"
elif report == "Lock Report":
    date_cond("l.lock_date")
    sql = ("SELECT a.application_number, s.service_name, d.district_name,"
           " l.lock_date, u.employee_name AS locked_by, l.relock_date" + JOINS
           + " JOIN tblLockUnlock l ON l.application_id = a.application_id"
             " LEFT JOIN tblUsers u ON u.user_id = l.locked_by")
    order = " ORDER BY l.lock_date DESC"
elif report == "Unlock Report":
    date_cond("l.unlock_requested_at")
    conds.append("l.unlock_status IS NOT NULL")
    sql = ("SELECT a.application_number, s.service_name, d.district_name,"
           " l.unlock_reason, l.unlock_status, r.employee_name AS requested_by,"
           " l.unlock_requested_at, ap.employee_name AS decided_by, l.unlock_date"
           + JOINS
           + " JOIN tblLockUnlock l ON l.application_id = a.application_id"
             " LEFT JOIN tblUsers r ON r.user_id = l.unlock_requested_by"
             " LEFT JOIN tblUsers ap ON ap.user_id = l.unlock_approved_by")
    order = " ORDER BY l.unlock_requested_at DESC"
elif report == "User Activity Report":
    # Activity is per user, so the record filters do not apply; dates do.
    conds = ["1 = 1"]
    params = []
    date_cond("al.timestamp")
    sql = ("SELECT al.username, u.employee_name, r.role_name,"
           " COUNT(*) AS actions,"
           " SUM(CASE WHEN al.activity = 'Login' THEN 1 ELSE 0 END) AS logins,"
           " MAX(al.timestamp) AS last_action"
           "  FROM tblAuditLogs al"
           "  LEFT JOIN tblUsers u ON u.user_id = al.user_id"
           "  LEFT JOIN tblUserRoles ur ON ur.user_id = u.user_id"
           "  LEFT JOIN tblRoles r ON r.role_id = ur.role_id")
    order = " GROUP BY al.username ORDER BY actions DESC"
else:  # Audit Report
    conds = ["1 = 1"]
    params = []
    date_cond("al.timestamp")
    sql = ("SELECT al.timestamp, al.username, al.activity, al.module, al.entity,"
           " al.entity_id, al.old_value, al.new_value, al.ip_address"
           "  FROM tblAuditLogs al")
    order = " ORDER BY al.timestamp DESC"

where = " WHERE " + " AND ".join(conds)
frame = db.frame(sql + where + order + " LIMIT 5000", params)

ui.section(report, f"{len(frame):,} row(s)"
           + (" — the first 5,000 are shown." if len(frame) == 5000 else "."))
if frame.empty:
    ui.empty_state("No rows for these filters.", ":material/search_off:")
else:
    ui.table(frame, columns={}, height=440)
    ui.download_row(frame, report.lower().replace(" ", "-"), report,
                    save_to_sharepoint=True)
