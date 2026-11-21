"""Login, session, role-based access control and data scope.

Module 1 of the blueprint. Permissions come from tblRolePermissions, and the
data a signed-in user may see comes from their role's scope: state-wide,
one division, one district, or nothing beyond what is already shared.
"""

from __future__ import annotations

import streamlit as st

from app import db

SESSION_KEY = "rtps_user"
SESSION_TIMEOUT_MINUTES = 30

DEMO_ACCOUNTS = [
    ("superadmin", "Super Admin", "Everything, every district"),
    ("stateadmin", "State Admin", "State review and final approval, unlock approval"),
    ("divadmin.patna", "Division Admin", "Read-only across the Patna division"),
    ("distadmin.patna", "District Admin", "District approval, lock, unlock request"),
    ("reviewer.patna", "Reviewer", "District Reviewer approval level"),
    ("verifier.patna", "Verifier", "QAP verification and raising corrections"),
    ("operator.patna", "Operator", "Entry, submission and correction response"),
    ("readonly", "Read Only", "Views records and reports only"),
]


def _load(username: str) -> dict | None:
    row = db.one(
        """
        SELECT u.*, r.role_name, r.scope, r.role_level,
               dm.district_name, dv.division_name
          FROM tblUsers u
          JOIN tblUserRoles ur ON ur.user_id = u.user_id
          JOIN tblRoles r      ON r.role_id  = ur.role_id
     LEFT JOIN tblDistrictMaster dm ON dm.district_id = u.district_id
     LEFT JOIN tblDivisionMaster dv ON dv.division_id = u.division_id
         WHERE u.username = ?
        """,
        (username,),
    )
    return dict(row) if row else None


def permissions(role_name: str) -> set[str]:
    rows = db.query(
        """
        SELECT p.permission_code
          FROM tblRolePermissions rp
          JOIN tblRoles r       ON r.role_id = rp.role_id
          JOIN tblPermissions p ON p.permission_id = rp.permission_id
         WHERE r.role_name = ?
        """,
        (role_name,),
    )
    return {r["permission_code"] for r in rows}


def authenticate(username: str, password: str) -> tuple[dict | None, str | None]:
    user = _load(username.strip())
    if not user:
        return None, "No account with that username."
    if user["status"] != "Active":
        return None, "This account is disabled. Ask an administrator to re-enable it."
    if db.hash_password(password, user["salt"]) != user["password_hash"]:
        return None, "Wrong password."
    return user, None


def sign_in(user: dict) -> None:
    user = dict(user)
    user["permissions"] = permissions(user["role_name"])
    st.session_state[SESSION_KEY] = user
    import time

    st.session_state["rtps_last_seen"] = time.time()
    db.execute(
        "UPDATE tblUsers SET last_login = datetime('now') WHERE user_id = ?",
        (user["user_id"],),
    )
    from app import audit

    audit.log("Login", "Login & Security", "tblUsers", user["username"],
              new_value="Success", user=user)


def sign_out() -> None:
    user = current_user()
    if user:
        from app import audit

        audit.log("Logout", "Login & Security", "tblUsers", user["username"],
                  new_value="Signed out", user=user)
    st.session_state.pop(SESSION_KEY, None)


def session_expired() -> bool:
    """True once the user has been idle longer than the configured timeout."""
    import time

    limit = int(db.setting("session_timeout_minutes", str(SESSION_TIMEOUT_MINUTES)))
    now = time.time()
    last = st.session_state.get("rtps_last_seen", now)
    st.session_state["rtps_last_seen"] = now
    return (now - last) > limit * 60


def current_user() -> dict | None:
    return st.session_state.get(SESSION_KEY)


def user() -> dict:
    u = current_user()
    if u is None:
        st.error("Your session has ended. Sign in again.", icon=":material/lock:")
        st.stop()
    return u


def has(*codes: str) -> bool:
    u = current_user()
    if not u:
        return False
    return any(c in u["permissions"] for c in codes)


def require(*codes: str) -> dict:
    u = user()
    if not has(*codes):
        st.error(
            f"Your role — {u['role_name']} — cannot open this screen. "
            "Ask an administrator if you need it.",
            icon=":material/block:",
        )
        st.stop()
    return u


def scope_clause(alias: str = "a") -> tuple[str, list]:
    """SQL fragment limiting applications to what this user may see."""
    u = current_user()
    if not u:
        return "1 = 0", []
    scope = u["scope"]
    if scope == "state" or u["role_name"] == "Read Only":
        return "1 = 1", []
    if scope == "division" and u["division_id"]:
        return (
            f"{alias}.district_id IN "
            "(SELECT district_id FROM tblDistrictMaster WHERE division_id = ?)",
            [u["division_id"]],
        )
    if scope == "district" and u["district_id"]:
        return f"{alias}.district_id = ?", [u["district_id"]]
    return "1 = 0", []


def scope_label() -> str:
    u = current_user()
    if not u:
        return "—"
    if u["scope"] == "state" or u["role_name"] == "Read Only":
        return "All districts"
    if u["scope"] == "division" and u["division_name"]:
        return f"{u['division_name']} division"
    if u["scope"] == "district" and u["district_name"]:
        return f"{u['district_name']} district"
    return "No data scope"


def districts_in_scope() -> list[dict]:
    where, params = scope_clause("d")
    rows = db.query(
        "SELECT d.district_id, d.district_name, v.division_name"
        "  FROM tblDistrictMaster d"
        "  JOIN tblDivisionMaster v ON v.division_id = d.division_id"
        f" WHERE d.status = 'Active' AND {where}"
        " ORDER BY d.district_name",
        params,
    )
    return [dict(r) for r in rows]
