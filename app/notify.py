"""Module 12 — one place that raises a notification for a workflow event."""

from __future__ import annotations

from app import db

EVENTS = [
    "New Submission",
    "Correction Raised",
    "Correction Assigned",
    "Approval Completed",
    "Application Rejected",
    "Lock Applied",
    "Unlock Approved",
]


def send(
    user_id: int | None,
    event: str,
    message: str,
    application_id: int | None = None,
    channel: str = "In-App",
    kind: str = "Info",
) -> None:
    if user_id is None:
        return
    db.execute(
        "INSERT INTO tblNotifications(user_id, application_id, event, message,"
        " channel, type, status, sent_time, read_flag)"
        " VALUES (?,?,?,?,?,?, 'Sent', datetime('now'), 0)",
        (user_id, application_id, event, message, channel, kind),
    )


def unread_count(user_id: int) -> int:
    return db.scalar(
        "SELECT COUNT(*) FROM tblNotifications WHERE user_id = ? AND read_flag = 0",
        (user_id,),
    )
