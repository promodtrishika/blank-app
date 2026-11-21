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

def microsoft_button() -> None:
    if st.button("Sign in with Microsoft 365", type="primary",
                 icon=":material/account_circle:", width="stretch",
                 key="m365_login"):
        st.login("microsoft")


def password_form() -> None:
    with st.form("login", border=True):
        st.subheader("Sign in", anchor=False)
        username = st.text_input("Username", autocomplete="username")
        password = st.text_input("Password", type="password",
                                 autocomplete="current-password")
        mfa_on = db.setting("mfa_required", "1") == "1"
        otp = st.text_input(
            "One-time passcode" + (" *" if mfa_on else ""), max_chars=6,
            help="Multi-factor is stubbed for portal passwords: any six digits "
                 "pass. Settings can switch it off.")
        submitted = st.form_submit_button(
            "Sign in", type="secondary" if auth.microsoft_configured() else "primary",
            icon=":material/login:", width="stretch")
    if submitted:
        if not username or not password:
            st.error("Enter both a username and a password.", icon=":material/error:")
        elif mfa_on and (len(otp) != 6 or not otp.isdigit()):
            st.error("Enter the six-digit one-time passcode.", icon=":material/error:")
        else:
            user, problem = auth.authenticate(username, password)
            if problem:
                st.error(problem, icon=":material/error:")
            else:
                auth.sign_in(user)
                st.rerun()


def login_screen(problem: str | None = None) -> None:
    """Screen 01 — Login."""
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.title(":material/verified_user: RTPS QAP Portal", anchor=False)
        st.caption(
            "Quality Assurance Portal for Right to Public Services — "
            "verification, correction, approval, lock and audit in one place."
        )
        if problem:
            st.error(problem, icon=":material/person_off:")
            if auth.microsoft_signed_in():
                # Signed in to Microsoft 365 with an account the portal does not
                # know: the only useful next step is another account.
                if st.button("Use a different Microsoft 365 account", type="primary",
                             icon=":material/switch_account:"):
                    st.logout()
                return
        if auth.microsoft_configured():
            with st.container(border=True):
                st.subheader("Sign in", anchor=False)
                st.caption("Use your Microsoft 365 work account. Multi-factor "
                           "authentication is whatever your organisation requires.")
                microsoft_button()
        if auth.passwords_allowed():
            if auth.microsoft_configured():
                st.caption("Or, with a portal password:")
            password_form()
        elif not auth.microsoft_configured():
            st.error(
                "The portal keeps its data in SharePoint, so sign-in is through "
                "Microsoft 365 — and Microsoft 365 sign-in is not configured. Add "
                "the [auth] and [auth.microsoft] sections to .streamlit/secrets.toml "
                "(see docs/SHAREPOINT.md).", icon=":material/settings:")
    with right:
        if auth.passwords_allowed():
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
        else:
            st.subheader("Data in SharePoint", anchor=False, divider="gray")
            st.caption(
                "Applications, verifications, corrections, approvals and the audit "
                "trail are stored in SharePoint lists; attachments and saved reports "
                "in SharePoint document libraries.")
            st.markdown(f":material/cloud: {db.store().config.site_url}")


def sidebar_identity(user: dict) -> None:
    with st.sidebar:
        st.markdown(f"**{user['employee_name']}**")
        st.caption(f"{user['designation'] or '—'} · {user['role_name']}")
        st.caption(f":material/map: {auth.scope_label()}")
        unread = notify.unread_count(user["user_id"])
        if unread:
            st.markdown(f":orange-badge[:material/notifications_active: "
                        f"{unread} unread]")
        # Filled at the end of the run, after this page's changes were sent.
        st.session_state["_sync_slot"] = st.empty()
        if st.button("Sign out", icon=":material/logout:", width="stretch"):
            auth.sign_out()
            st.rerun()
        st.divider()


def sync_status() -> None:
    """One line in the sidebar saying whether SharePoint has every change."""
    store = db.store()
    slot = st.session_state.pop("_sync_slot", None)
    if store is None or slot is None:
        return
    status = store.status()
    with slot.container():
        if status["pending"]:
            st.markdown(f":orange-badge[:material/cloud_sync: {status['pending']} "
                        "change(s) waiting for SharePoint]")
            if status["last_error"]:
                st.caption(status["last_error"][:160])
        elif status["last_error"]:
            st.markdown(":orange-badge[:material/cloud_off: SharePoint not answering]")
            st.caption(status["last_error"][:160])
        else:
            st.markdown(":green-badge[:material/cloud_done: Saved to SharePoint]")


def public_url() -> str:
    """The portal's own address, for links that leave a frame."""
    import os

    if os.environ.get("RTPS_PUBLIC_URL"):
        return os.environ["RTPS_PUBLIC_URL"].rstrip("/")
    if os.environ.get("WEBSITE_HOSTNAME"):            # set by Azure App Service
        return f"https://{os.environ['WEBSITE_HOSTNAME']}"
    return "/"


def teams_launcher() -> None:
    """What the Teams tab shows. Microsoft's sign-in page refuses to open
    inside a frame, so the portal itself opens in the browser."""
    st.title(":material/verified_user: RTPS QAP Portal", anchor=False)
    st.caption("Quality Assurance Portal for Right to Public Services.")
    with st.container(border=True):
        st.markdown("The portal opens in your browser, where you sign in with your "
                    "Microsoft 365 account.")
        st.link_button("Open the RTPS QAP Portal", public_url(), type="primary",
                       icon=":material/open_in_new:", width="stretch")
    st.caption("Microsoft does not allow its sign-in page inside a Teams tab, so "
               "the portal cannot run inside Teams itself.")


def main() -> None:
    if st.query_params.get("from") == "teams":
        teams_launcher()
        return
    try:
        db.connect()
    except Exception as exc:          # SharePoint unreachable on first load
        st.title(":material/cloud_off: RTPS QAP Portal", anchor=False)
        st.error(str(exc), icon=":material/cloud_off:")
        st.caption("The portal retries every time this page is opened.")
        return
    db.refresh()
    try:
        run()
    finally:
        # Every write this run made goes to SharePoint now — including on
        # st.rerun(), which unwinds through here.
        db.flush()
    sync_status()


def run() -> None:
    problem = auth.complete_microsoft_sign_in()
    user = auth.current_user()
    if user is None:
        login_screen(problem)
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
