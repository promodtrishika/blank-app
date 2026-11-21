"""Screen 06 — Submission List (blueprint module 3)."""

from __future__ import annotations

import streamlit as st

from app import auth, db, theme, ui

user = auth.require("app.view")

ui.page_header("Submission List",
               "Every application in your scope, with the filters the blueprint names.",
               ":material/list_alt:")

filters = ui.filter_row(key="subs", statuses=theme.APP_STATUSES)
where, params = ui.where_from_filters(filters)

frame = ui.applications(where, params,
                        order="COALESCE(a.submitted_at, a.created_at) DESC")

if frame.empty:
    ui.empty_state("No application matches these filters. Widen them and try again.")
    st.stop()

st.caption(f"{len(frame):,} application(s). The newest sit at the top.")
columns = dict(ui.APPLICATION_COLUMNS)
view = frame[["application_number", "applicant_name", "service_name",
              "district_name", "status", "current_level", "score",
              "submission_date", "age_days"]]
ui.table(view, columns=columns, height=430)
ui.download_row(view, "submission-list")

ui.section("Status mix in this result")
cols = st.columns(min(4, max(1, frame["status"].nunique())))
for col, (status, n) in zip(cols * 3, frame["status"].value_counts().items()):
    with col:
        ui.badge(status)
        st.caption(f"{n:,} application(s)")

with st.expander("Submission history of one application"):
    picked = ui.pick_application(frame, key="subs_pick")
    if picked:
        history = db.frame(
            "SELECT 'Status' AS kind, activity AS detail, new_value AS outcome,"
            " username AS actor, timestamp AS at FROM tblAuditLogs"
            " WHERE entity_id = ? ORDER BY timestamp DESC",
            [picked["application_number"]])
        if history.empty:
            ui.empty_state("No recorded history for this application yet.",
                           ":material/history:")
        else:
            ui.table(history, columns={
                "kind": st.column_config.TextColumn("Kind"),
                "detail": st.column_config.TextColumn("Activity", width="medium"),
                "outcome": st.column_config.TextColumn("Outcome"),
                "actor": st.column_config.TextColumn("By"),
                "at": st.column_config.TextColumn("When"),
            })
