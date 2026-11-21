"""Screen 02 — Dashboard (blueprint module 2)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app import auth, charts, db, theme, ui

user = auth.require("app.view")

ui.page_header("Dashboard", f"Live position for {auth.scope_label().lower()}.",
               ":material/space_dashboard:")

filters = ui.filter_row(key="dash", statuses=None)
where, params = ui.where_from_filters(filters)


def count(extra: str = "", extra_params: list | None = None) -> int:
    sql = f"SELECT COUNT(*) FROM tblApplications a WHERE {where}"
    if extra:
        sql += f" AND {extra}"
    return db.scalar(sql, params + (extra_params or []))


total = count()
approved = count("a.status IN ('Approved','Locked')")
rejected = count("a.status = 'Rejected'")
locked = count("a.status = 'Locked'")
pending_verification = count("a.status = 'Submitted'")
pending_approval = count("a.status = 'Under Verification'")
pending_correction = count("a.status = 'Correction Required'")
drafts = count("a.status = 'Draft'")
today = count("date(a.submitted_at) = date('now')")
unlock_requests = db.scalar(
    "SELECT COUNT(*) FROM tblLockUnlock l JOIN tblApplications a"
    f" ON a.application_id = l.application_id WHERE {where}"
    " AND l.unlock_status = 'Requested'"
    # The newest lock row is a record's current state — the Lock / Unlock
    # screen counts the same way, so the two numbers always agree.
    " AND l.lock_id = (SELECT MAX(x.lock_id) FROM tblLockUnlock x"
    "                   WHERE x.application_id = l.application_id)", params)
avg_days = db.scalar(
    "SELECT AVG(julianday(a.approved_at) - julianday(a.submitted_at))"
    f" FROM tblApplications a WHERE {where} AND a.approved_at IS NOT NULL", params,
    default=0.0) or 0.0
decided = approved + rejected
approval_rate = (approved / decided * 100) if decided else 0.0

ui.kpi_row([
    ("Total applications", f"{total:,}"),
    ("Submitted today", f"{today:,}"),
    ("Pending verification", f"{pending_verification:,}",
     "Submitted, not yet verified against the QAP checklist."),
    ("Pending approval", f"{pending_approval:,}",
     "Verified and somewhere in the four approval levels."),
    ("Corrections pending", f"{pending_correction:,}"),
    ("Approved", f"{approved:,}", "Approved records, locked ones included."),
    ("Rejected", f"{rejected:,}"),
    ("Locked", f"{locked:,}"),
    ("Unlock requests", f"{unlock_requests:,}"),
    ("Drafts", f"{drafts:,}"),
    ("Approval rate", f"{approval_rate:.1f}%",
     "Approved as a share of everything decided."),
    ("Average processing time", f"{avg_days:.1f} days",
     "Submission to final approval."),
])

ui.section("Monthly trend", "Submitted, approved and rejected, by month. The current month is to date.")
trend_sql = f"""
WITH scoped AS (SELECT * FROM tblApplications a WHERE {where})
SELECT month, series, COUNT(*) AS applications FROM (
    SELECT strftime('%Y-%m', submitted_at) AS month, 'Submitted' AS series
      FROM scoped WHERE submitted_at IS NOT NULL
    UNION ALL
    SELECT strftime('%Y-%m', approved_at), 'Approved' FROM scoped
     WHERE approved_at IS NOT NULL
    UNION ALL
    SELECT strftime('%Y-%m', updated_at), 'Rejected' FROM scoped
     WHERE status = 'Rejected'
) GROUP BY month, series ORDER BY month
"""
trend = db.frame(trend_sql, params)
charts.trend(trend, x="month", y="applications", series="series",
             order=["Submitted", "Approved", "Rejected"],
             x_title="Month", y_title="Applications")

PERFORMANCE = """
SELECT {label} AS {alias},
       ROUND(100.0 * SUM(CASE WHEN julianday(COALESCE(a.approved_at, a.updated_at))
                                   - julianday(a.submitted_at) <= s.sla_days
                              THEN 1 ELSE 0 END) / COUNT(*), 1) AS within_sla_pct
  FROM tblApplications a
  JOIN tblServiceMaster s  ON s.service_id = a.service_id
  JOIN tblDistrictMaster d ON d.district_id = a.district_id
  JOIN tblDivisionMaster v ON v.division_id = d.division_id
 WHERE {where} AND a.status IN ('Approved', 'Locked', 'Rejected')
 GROUP BY {label} HAVING COUNT(*) >= 3
"""

left, right = st.columns(2, gap="large")
with left:
    district_perf = db.frame(PERFORMANCE.format(label="d.district_name",
                                                alias="district", where=where), params)
    ui.section("District performance",
               "Decided records disposed within the service SLA. "
               + (f"The 12 lowest of {len(district_perf)}; Analytics ranks them all."
                  if len(district_perf) > 12 else ""))
    charts.ranked_bar(district_perf.sort_values("within_sla_pct").head(12),
                      label="district", value="within_sla_pct",
                      value_title="Within SLA (%)")
with right:
    ui.section("Division performance", "The same measure, one row per division.")
    charts.ranked_bar(
        db.frame(PERFORMANCE.format(label="v.division_name", alias="division",
                                    where=where), params),
        label="division", value="within_sla_pct", value_title="Within SLA (%)")

left, right = st.columns(2, gap="large")
with left:
    ui.section("Service volume", "Applications on record, by service.")
    charts.ranked_bar(
        db.frame(
            "SELECT s.service_name AS service, COUNT(*) AS applications"
            "  FROM tblApplications a"
            "  JOIN tblServiceMaster s ON s.service_id = a.service_id"
            f" WHERE {where} GROUP BY s.service_name"
            " ORDER BY applications DESC", params),
        label="service", value="applications", value_title="Applications")
with right:
    ui.section("Approval chain", "Where the records still in the chain are sitting.")
    rows = db.query(
        "SELECT a.current_level AS level, COUNT(*) AS n FROM tblApplications a"
        f" WHERE {where} AND a.status = 'Under Verification'"
        " GROUP BY a.current_level", params)
    counts = {r["level"]: r["n"] for r in rows}
    from app.workflow import LEVELS

    charts.funnel([(level, counts.get(level, 0)) for level in LEVELS])

ui.section("Status mix")
mix = db.frame(
    "SELECT a.status, COUNT(*) AS applications FROM tblApplications a"
    f" WHERE {where} GROUP BY a.status", params)
if mix.empty:
    ui.empty_state("No applications match these filters.")
else:
    mix["status"] = pd.Categorical(mix["status"], theme.APP_STATUSES, ordered=True)
    mix = mix.sort_values("status")
    rows = list(mix.itertuples())
    for start in range(0, len(rows), 4):
        cols = st.columns(4)
        for col, row in zip(cols, rows[start:start + 4]):
            with col, st.container(border=True):
                ui.badge(str(row.status))
                st.metric(str(row.status), f"{row.applications:,}",
                          label_visibility="collapsed")
