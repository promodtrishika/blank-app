"""Module 11 — the one helper every write in the portal calls.

Nothing records an action twice and nothing records it its own way: a screen
that changes data calls log() and the audit trail stays complete.
"""

from __future__ import annotations

import streamlit as st

from app import db


def _client() -> tuple[str | None, str | None]:
    ip = browser = None
    try:
        ctx = st.context
        ip = getattr(ctx, "ip_address", None)
        headers = getattr(ctx, "headers", None) or {}
        browser = headers.get("User-Agent") or headers.get("user-agent")
    except Exception:  # pragma: no cover - bare script runs
        pass
    # Anything that is not a plain string (absent context, a test double) is
    # recorded as unknown rather than written into the trail.
    ip = ip if isinstance(ip, str) else None
    browser = browser[:120] if isinstance(browser, str) else None
    return ip, browser


def log(
    activity: str,
    module: str,
    entity: str | None = None,
    entity_id: str | int | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
    user: dict | None = None,
) -> None:
    if user is None:
        user = st.session_state.get("rtps_user")
    ip, browser = _client()
    db.execute(
        "INSERT INTO tblAuditLogs(user_id, username, activity, module, entity,"
        " entity_id, old_value, new_value, ip_address, browser, timestamp)"
        " VALUES (?,?,?,?,?,?,?,?,?,?, datetime('now'))",
        (
            (user or {}).get("user_id"),
            (user or {}).get("username", "anonymous"),
            activity,
            module,
            entity,
            str(entity_id) if entity_id is not None else None,
            old_value,
            new_value,
            ip,
            browser,
        ),
    )
