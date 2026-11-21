"""Screen 14 — Notification Centre (blueprint module 12)."""

from __future__ import annotations

import streamlit as st

from app import auth, db, notify, ui

user = auth.require("notify.view")

ui.page_header("Notification Centre",
               "What the workflow has told you, by email, SMS and in-app.",
               ":material/notifications:")

mine = db.frame(
    "SELECT n.notification_id, n.event, n.message, n.channel, n.type, n.status,"
    " n.sent_time, n.read_flag, a.application_number"
    "  FROM tblNotifications n"
    "  LEFT JOIN tblApplications a ON a.application_id = n.application_id"
    " WHERE n.user_id = ? ORDER BY n.sent_time DESC", [user["user_id"]])

unread = int((mine["read_flag"] == 0).sum()) if not mine.empty else 0
ui.kpi_row([
    ("Unread", f"{unread:,}"),
    ("All notifications", f"{len(mine):,}"),
    ("Needing action",
     f"{int((mine['type'] == 'Action').sum()) if not mine.empty else 0:,}"),
    ("Channels", "Email · SMS · In-App"),
])

cols = st.columns([2, 2, 1])
with cols[0]:
    show = st.segmented_control("Show", ["Unread", "All"], default="Unread",
                                key="notif_show")
with cols[1]:
    events = st.multiselect("Event", notify.EVENTS, placeholder="Any event",
                            key="notif_event")
with cols[2]:
    st.write("")
    if st.button("Mark all read", icon=":material/done_all:", width="stretch",
                 disabled=unread == 0):
        db.execute("UPDATE tblNotifications SET read_flag = 1 WHERE user_id = ?",
                   (user["user_id"],))
        st.rerun()

view = mine
if not view.empty and show == "Unread":
    view = view[view["read_flag"] == 0]
if not view.empty and events:
    view = view[view["event"].isin(events)]

if view.empty:
    ui.empty_state("Nothing here. New workflow events will appear as they happen.",
                   ":material/notifications_off:")
    st.stop()

ICON = {"Action": ":material/assignment_late:", "Alert": ":material/warning:",
        "Success": ":material/check_circle:", "Info": ":material/info:"}
for r in view.head(60).itertuples():
    with st.container(border=True):
        top = st.columns([6, 2])
        with top[0]:
            st.markdown(f"{ICON.get(r.type, ':material/info:')} **{r.event}**"
                        + ("" if r.read_flag else "  :blue-badge[New]"))
            st.write(r.message)
            st.caption(f"{r.channel} · {r.sent_time}"
                       + (f" · {r.application_number}" if r.application_number else ""))
        with top[1]:
            if not r.read_flag and st.button(
                    "Mark read", key=f"read_{r.notification_id}",
                    icon=":material/done:", width="stretch"):
                db.execute("UPDATE tblNotifications SET read_flag = 1"
                           " WHERE notification_id = ?", (r.notification_id,))
                st.rerun()
if len(view) > 60:
    st.caption(f"Showing the newest 60 of {len(view):,}.")
