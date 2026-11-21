"""Screen 18 — Analytics Dashboard (blueprint module 14)."""

from __future__ import annotations

import streamlit as st

from app import auth, charts, db, ui

user = auth.require("analytics.view")

ui.page_header("Analytics",
               "Rankings and rates across districts, divisions and services.",
               ":material/insights:")

filters = ui.filter_row(key="ana", statuses=None, with_text=False)
where, params = ui.where_from_filters(filters)

total = db.scalar(f"SELECT COUNT(*) FROM tblApplications a WHERE {where}", params)
by_status = {r["status"]: r["n"] for r in db.query(
    f"SELECT a.status, COUNT(*) AS n FROM tblApplications a WHERE {where}"
    " GROUP BY a.status", params)}
approved = by_status.get("Approved", 0) + by_status.get("Locked", 0)
rejected = by_status.get("Rejected", 0)
pending = sum(by_status.get(s, 0) for s in
              ("Submitted", "Under Verification", "Correction Required"))
filed = total - by_status.get("Draft", 0)


def pct(n: int, d: int) -> str:
    return f"{(n / d * 100) if d else 0:.1f}%"


avg_approval = db.scalar(
    "SELECT AVG(julianday(a.approved_at) - julianday(a.submitted_at))"
    f" FROM tblApplications a WHERE {where} AND a.approved_at IS NOT NULL",
    params, default=0.0) or 0.0
avg_correction = db.scalar(
    "SELECT AVG(julianday(COALESCE(c.responded_at, c.closed_at))"
    " - julianday(c.raised_at)) FROM tblCorrections c"
    " JOIN tblApplications a ON a.application_id = c.application_id"
    f" WHERE {where} AND COALESCE(c.responded_at, c.closed_at) IS NOT NULL",
    params, default=None)

beyond_sla = db.scalar(
    "SELECT COUNT(*) FROM tblApplications a"
    " JOIN tblServiceMaster s ON s.service_id = a.service_id"
    f" WHERE {where}"
    " AND a.status IN ('Submitted', 'Under Verification', 'Correction Required')"
    " AND julianday('now') - julianday(a.submitted_at) > s.sla_days", params)
avg_score = db.scalar(
    f"SELECT AVG(a.score) FROM tblApplications a WHERE {where}"
    " AND a.score IS NOT NULL", params, default=0.0) or 0.0

ui.kpi_row([
    ("Average approval time", f"{avg_approval:.1f} days",
     "Submission to final State Approval."),
    ("Average correction time",
     f"{avg_correction:.1f} days" if avg_correction is not None else "No data yet",
     "Correction raised to operator response."),
    ("Approval rate", pct(approved, approved + rejected),
     "Approved among decided records."),
    ("Rejection rate", pct(rejected, approved + rejected)),
    ("Pending rate", pct(pending, filed),
     "Submitted, in verification or in correction, among everything filed."),
    ("Filed applications", f"{filed:,}"),
    ("Beyond SLA", f"{beyond_sla:,}", "Still pending past the service's SLA."),
    ("Average QAP score", f"{avg_score:.1f}"),
])

ui.section("Submission trend", "Filed, approved and rejected per month. The current month is to date.")
trend = db.frame(f"""
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
) GROUP BY month, series ORDER BY month""", params)
charts.trend(trend, x="month", y="applications", series="series",
             order=["Submitted", "Approved", "Rejected"],
             x_title="Month", y_title="Applications")

RANK_SQL = """
SELECT {label} AS name,
       COUNT(*) AS filed,
       SUM(CASE WHEN a.status IN ('Approved','Locked') THEN 1 ELSE 0 END) AS approved,
       SUM(CASE WHEN a.status = 'Rejected' THEN 1 ELSE 0 END) AS rejected,
       ROUND(100.0 * SUM(CASE WHEN a.status IN ('Approved','Locked','Rejected')
                 AND julianday(COALESCE(a.approved_at, a.updated_at))
                     - julianday(a.submitted_at) <= s.sla_days THEN 1 ELSE 0 END)
             / NULLIF(SUM(CASE WHEN a.status IN ('Approved','Locked','Rejected')
                          THEN 1 ELSE 0 END), 0), 1) AS within_sla_pct,
       ROUND(AVG(a.score), 1) AS avg_score,
       ROUND(AVG(CASE WHEN a.approved_at IS NOT NULL THEN
             julianday(a.approved_at) - julianday(a.submitted_at) END), 1) AS avg_days
  FROM tblApplications a
  JOIN tblDistrictMaster d ON d.district_id = a.district_id
  JOIN tblDivisionMaster v ON v.division_id = d.division_id
  JOIN tblServiceMaster s  ON s.service_id = a.service_id
 WHERE {where} AND a.status <> 'Draft'
 GROUP BY {label}
"""


def ranking(label: str):
    frame = db.frame(RANK_SQL.format(label=label, where=where), params)
    if frame.empty:
        return frame
    decided = (frame["approved"] + frame["rejected"]).where(lambda x: x > 0)
    frame["approval_pct"] = (frame["approved"] / decided * 100).round(1)
    # Composite rank: timeliness first (what RTPS measures), then approval
    # rate, then QAP score. Nothing decided yet means no rate — blank, ranked
    # last — never a 0% that reads as failure.
    frame = frame.sort_values(["within_sla_pct", "approval_pct", "avg_score"],
                              ascending=[False, False, False],
                              na_position="last").reset_index(drop=True)
    frame.insert(0, "rank", frame.index + 1)
    return frame


RANK_COLUMNS = {
    "rank": st.column_config.NumberColumn("Rank", format="%d"),
    "name": st.column_config.TextColumn("Name", width="medium"),
    "filed": st.column_config.NumberColumn("Filed", format="%d"),
    "approved": st.column_config.NumberColumn("Approved", format="%d"),
    "rejected": st.column_config.NumberColumn("Rejected", format="%d"),
    "within_sla_pct": st.column_config.ProgressColumn("Within SLA", format="%.1f%%",
                                                      min_value=0, max_value=100),
    "approval_pct": st.column_config.NumberColumn("Approval rate", format="%.1f%%"),
    "avg_score": st.column_config.NumberColumn("Avg QAP score", format="%.1f"),
    "avg_days": st.column_config.NumberColumn("Avg days to approve", format="%.1f"),
}

district_tab, division_tab, service_tab = st.tabs(
    ["District ranking", "Division ranking", "Service ranking"])
for tab, label, title in ((district_tab, "d.district_name", "District"),
                          (division_tab, "v.division_name", "Division"),
                          (service_tab, "s.service_name", "Service")):
    with tab:
        frame = ranking(label)
        if frame.empty:
            ui.empty_state("No filed applications match these filters.")
            continue
        st.caption("Ranked by the share of decided records disposed within the "
                   "service SLA, then by approval rate, then by QAP score.")
        ordered = frame[["rank", "name", "within_sla_pct", "filed", "approved",
                         "rejected", "approval_pct", "avg_score", "avg_days"]]
        ui.table(ordered, columns=RANK_COLUMNS, height=min(420, 38 + 35 * len(frame)))
        ui.download_row(ordered, f"{title.lower()}-ranking", f"{title} Ranking")
        undecided = int(frame["within_sla_pct"].isna().sum())
        if undecided:
            st.caption(f"{undecided} with nothing decided yet are left out of the "
                       "chart; they rank last in the table.")
        charts.ranked_bar(frame.dropna(subset=["within_sla_pct"])
                          .rename(columns={"name": title.lower()}),
                          label=title.lower(), value="within_sla_pct",
                          value_title="Within SLA (%)")
