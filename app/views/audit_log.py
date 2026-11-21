"""Screen 13 — Audit Log (blueprint module 11)."""

from __future__ import annotations

import streamlit as st

from app import auth, db, ui

user = auth.require("audit.view")

ui.page_header("Audit Log",
               "Every login, change, decision, lock and user edit, with who, when, "
               "where from, and the value before and after.",
               ":material/history:")

modules = [r["module"] for r in db.query(
    "SELECT DISTINCT module FROM tblAuditLogs ORDER BY module")]
cols = st.columns([2, 2, 2, 3])
with cols[0]:
    text = st.text_input("Search", placeholder="Username, record or value",
                         key="audit_text")
with cols[1]:
    pick_modules = st.multiselect("Module", modules, placeholder="Any module",
                                  key="audit_module")
with cols[2]:
    activity = st.text_input("Activity contains", placeholder="Login, Approved…",
                             key="audit_activity")
with cols[3]:
    dates = st.date_input("Between", value=(), key="audit_dates")

conds, params = ["1 = 1"], []
if text:
    conds.append("(username LIKE ? OR entity_id LIKE ? OR new_value LIKE ?"
                 " OR old_value LIKE ?)")
    params += [f"%{text}%"] * 4
if pick_modules:
    conds.append(f"module IN ({','.join('?' * len(pick_modules))})")
    params += pick_modules
if activity:
    conds.append("activity LIKE ?")
    params.append(f"%{activity}%")
if isinstance(dates, (tuple, list)) and len(dates) == 2:
    conds.append("date(timestamp) BETWEEN ? AND ?")
    params += [str(dates[0]), str(dates[1])]

where = " AND ".join(conds)
total = db.scalar(f"SELECT COUNT(*) FROM tblAuditLogs WHERE {where}", params)
frame = db.frame(
    "SELECT audit_id, timestamp, username, activity, module, entity, entity_id,"
    " old_value, new_value, ip_address, browser"
    f"  FROM tblAuditLogs WHERE {where} ORDER BY timestamp DESC, audit_id DESC"
    " LIMIT 2000", params)

logins = db.scalar(f"SELECT COUNT(*) FROM tblAuditLogs WHERE {where}"
                   " AND activity = 'Login'", params)
people = db.scalar(f"SELECT COUNT(DISTINCT username) FROM tblAuditLogs WHERE {where}",
                   params)
module_count = db.scalar(f"SELECT COUNT(DISTINCT module) FROM tblAuditLogs"
                         f" WHERE {where}", params)
ui.kpi_row([
    ("Entries matching", f"{total:,}"),
    ("Logins", f"{logins:,}"),
    ("Distinct users", f"{people:,}"),
    ("Modules", f"{module_count:,}"),
])

if frame.empty:
    ui.empty_state("No audit entry matches these filters.", ":material/search_off:")
    st.stop()

ui.table(frame, height=480, columns={
    "audit_id": st.column_config.NumberColumn("ID", format="%d"),
    "timestamp": st.column_config.TextColumn("When"),
    "username": st.column_config.TextColumn("User"),
    "activity": st.column_config.TextColumn("Activity", width="medium"),
    "module": st.column_config.TextColumn("Module", width="medium"),
    "entity": st.column_config.TextColumn("Table"),
    "entity_id": st.column_config.TextColumn("Record", width="medium"),
    "old_value": st.column_config.TextColumn("Old value"),
    "new_value": st.column_config.TextColumn("New value"),
    "ip_address": st.column_config.TextColumn("IP address"),
    "browser": st.column_config.TextColumn("Browser", width="medium"),
})
if total > 2000:
    st.caption(f"Showing the newest 2,000 of {total:,}. Narrow the filters or "
               "export the Audit Report for more.")
ui.download_row(frame, "audit-log", "Audit Log")
