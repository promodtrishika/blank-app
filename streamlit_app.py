"""RTPS QAP Portal — entry point.

Screen 01 is the login gate below; every other screen is a page in
app/views, reached only when the signed-in role carries the permission for it.
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="RTPS QAP Portal",
    page_icon=":material/verified_user:",
    layout="wide",
    initial_sidebar_state="expanded",
)

from app import auth, db, notify, seed  # noqa: E402  (after set_page_config)
from app.navigation import PAGES  # noqa: E402

def login_screen() -> None:
    """Screen 01 — Login."""
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.title(":material/verified_user: RTPS QAP Portal", anchor=False)
        st.caption(
            "Quality Assurance Portal for Right to Public Services — "
            "verification, correction, approval, lock and audit in one place."
        )
        with st.form("login", border=True):
            st.subheader("Sign in", anchor=False)
            username = st.text_input("Username", autocomplete="username")
            password = st.text_input("Password", type="password",
                                     autocomplete="current-password")
            mfa_on = db.setting("mfa_required", "1") == "1"
            otp = st.text_input(
                "One-time passcode" + (" *" if mfa_on else ""), max_chars=6,
                help="Multi-factor is stubbed in this prototype: any six digits "
                     "pass. Settings can switch it off.")
            submitted = st.form_submit_button("Sign in", type="primary",
                                              icon=":material/login:",
                                              width="stretch")
        if submitted:
            if not username or not password:
                st.error("Enter both a username and a password.",
                         icon=":material/error:")
            elif mfa_on and (len(otp) != 6 or not otp.isdigit()):
                st.error("Enter the six-digit one-time passcode.",
                         icon=":material/error:")
            else:
                user, problem = auth.authenticate(username, password)
                if problem:
                    st.error(problem, icon=":material/error:")
                else:
                    auth.sign_in(user)
                    st.rerun()
    with right:
        st.subheader("Demo accounts", anchor=False, divider="gray")
        st.caption(
            f"Every account below uses the password `{seed.DEMO_PASSWORD}`. "
            "Each one lands on a different set of screens."
        )
        for username, role, what in auth.DEMO_ACCOUNTS:
            with st.container(border=True):
                st.markdown(f"`{username}` — **{role}**")
                st.caption(what)
        st.caption(
            "Operators, verifiers, reviewers and district admins exist for every "
            "district: swap `patna` for another district name in lower case, "
            "such as `verifier.gaya`."
        )


def sidebar_identity(user: dict) -> None:
    with st.sidebar:
        st.markdown(f"**{user['employee_name']}**")
        st.caption(f"{user['designation'] or '—'} · {user['role_name']}")
        st.caption(f":material/map: {auth.scope_label()}")
        unread = notify.unread_count(user["user_id"])
        if unread:
            st.markdown(f":orange-badge[:material/notifications_active: "
                        f"{unread} unread]")
        if st.button("Sign out", icon=":material/logout:", width="stretch"):
            auth.sign_out()
            st.rerun()
        st.divider()


def main() -> None:
    user = auth.current_user()
    if user is None:
        login_screen()
        return
    if auth.session_expired():
        auth.sign_out()
        st.warning("Your session timed out. Sign in again.",
                   icon=":material/timer_off:")
        login_screen()
        return

    sidebar_identity(user)
    groups: dict[str, list] = {}
    for path, title, icon, codes, group in PAGES:
        if auth.has(*codes):
            groups.setdefault(group, []).append(
                st.Page(path, title=title, icon=icon,
                        default=not any(groups.values())))
    if not groups:
        st.error(
            f"The role {user['role_name']} carries no screen permissions. "
            "Ask an administrator to review it.",
            icon=":material/block:")
        return
    st.navigation(groups, expanded=True).run()


main()
