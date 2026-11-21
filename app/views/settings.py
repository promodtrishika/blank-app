"""Screen 16 — Settings (blueprint section 6, security framework)."""

from __future__ import annotations

import time

import streamlit as st

from app import audit, auth, db, ui

user = auth.require("settings.manage")

ui.page_header("Settings",
               "Security, notification and QAP thresholds for the whole portal.",
               ":material/settings:")

current = {r["setting_key"]: dict(r) for r in db.query("SELECT * FROM tblSettings")}


def val(key: str) -> str:
    return current[key]["setting_value"]


with st.form("settings", border=True):
    ui.section("Security")
    row = st.columns(3)
    with row[0]:
        timeout = st.number_input("Session timeout (minutes)", 5, 240,
                                  int(val("session_timeout_minutes")), step=5)
    if auth.passwords_allowed():
        with row[1]:
            min_len = st.number_input("Minimum password length", 8, 32,
                                      int(val("password_min_length")))
        with row[2]:
            mfa = st.toggle("Ask for a one-time passcode at sign-in",
                            val("mfa_required") == "1")
    else:
        min_len, mfa = int(val("password_min_length")), val("mfa_required") == "1"
        with row[1]:
            st.caption("Sign-in is through Microsoft 365, so password rules and "
                       "multi-factor authentication are set in Microsoft Entra ID, "
                       "not here.")

    ui.section("Notification channels")
    row = st.columns(3)
    with row[0]:
        email = st.toggle("Email", val("notify_email") == "1")
    with row[1]:
        sms = st.toggle("SMS", val("notify_sms") == "1")
    with row[2]:
        inapp = st.toggle("In-app", val("notify_inapp") == "1")

    ui.section("Quality assurance")
    row = st.columns(2)
    with row[0]:
        pass_score = st.slider("Lowest QAP score that can pass", 0, 100,
                               int(val("qap_pass_score")), step=5)
    with row[1]:
        sla_warn = st.number_input("Warn this many days before an SLA breach", 0, 15,
                                   int(val("sla_warning_days")))
    save = st.form_submit_button("Save settings", type="primary",
                                 icon=":material/save:", width="stretch")

if save:
    new = {
        "session_timeout_minutes": str(int(timeout)),
        "password_min_length": str(int(min_len)),
        "mfa_required": "1" if mfa else "0",
        "notify_email": "1" if email else "0",
        "notify_sms": "1" if sms else "0",
        "notify_inapp": "1" if inapp else "0",
        "qap_pass_score": str(int(pass_score)),
        "sla_warning_days": str(int(sla_warn)),
    }
    changed = {k: v for k, v in new.items() if current[k]["setting_value"] != v}
    for k, v in changed.items():
        db.execute("UPDATE tblSettings SET setting_value = ?, updated_at = datetime('now'),"
                   " updated_by = ? WHERE setting_key = ?", (v, user["username"], k))
        audit.log("Setting changed", "Settings", "tblSettings", k,
                  old_value=current[k]["setting_value"], new_value=v, user=user)
    if changed:
        st.success(f"{len(changed)} setting(s) saved.", icon=":material/save:")
        st.rerun()
    else:
        st.info("Nothing changed.", icon=":material/info:")

ui.section("Security framework in this prototype",
           "What runs here, and what the production build replaces it with.")
st.dataframe(
    [
        {"Control": "Authentication",
         "Prototype": "Microsoft 365 (Entra ID) sign-in when configured; portal "
                      "passwords (salted SHA-256) only in local mode",
         "Production": "Azure AD SSO with JWT"},
        {"Control": "Multi-factor",
         "Prototype": "Entra ID's own MFA for Microsoft 365 sign-in; a stubbed "
                      "passcode for portal passwords",
         "Production": "Azure AD MFA"},
        {"Control": "Authorisation", "Prototype": "Role → permission matrix + data scope",
         "Production": "Same model, enforced in the .NET API"},
        {"Control": "Session timeout", "Prototype": "Idle timer from this page",
         "Production": "Token lifetime + idle timeout"},
        {"Control": "Audit logging", "Prototype": "Every write via one helper",
         "Production": "Same, to tblAuditLogs in SQL Server"},
        {"Control": "Transport", "Prototype": "Whatever serves Streamlit",
         "Production": "HTTPS only, HSTS"},
        {"Control": "Backup",
         "Prototype": "SharePoint mode: Microsoft 365 retention; local mode: "
                      "download the SQLite file below",
         "Production": "SQL Server scheduled backup + DR replica"},
    ],
    hide_index=True, width="stretch")

def _ago(ts: float | None) -> str:
    if not ts:
        return "never"
    seconds = int(time.time() - ts)
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    return f"{seconds // 3600} h ago"


store = db.store()
ui.section("SharePoint",
           "Where the portal's records, attachments and saved reports are kept.")
if store is None:
    st.caption("The portal is running on its local database. To keep the data in "
               "SharePoint instead, follow docs/SHAREPOINT.md.")
else:
    db.flush()          # this page's own writes first, so the numbers are current
    status = store.status()
    cfg = store.config
    ui.kpi_row([
        ("Changes waiting", f"{status['pending']:,}",
         "Saved in the portal and queued for SharePoint."),
        ("Last sent", _ago(status["last_push"])),
        ("Last checked for changes", _ago(status["last_pull"]),
         f"The portal checks SharePoint at most every {cfg.pull_interval_seconds}s."),
        ("Lists", f"{status['lists']}", f"Named {cfg.list_prefix}…"),
    ])
    st.markdown(f":material/cloud: [{cfg.site_url}]({cfg.site_url}) · documents in "
                f"**{cfg.documents_library}** · reports in **{cfg.reports_library}**")
    if status["last_error"]:
        st.warning(f"Last problem: {status['last_error']}", icon=":material/cloud_off:")
    cols = st.columns(3)
    with cols[0]:
        if st.button("Sync now", icon=":material/sync:", width="stretch"):
            with st.spinner("Sending and fetching changes…"):
                pushed = store.push()
                pulled = store.pull()
            st.success(f"Sent {pushed['pushed']}, could not send {pushed['failed']}; "
                       f"picked up {pulled['changed']} change(s).",
                       icon=":material/sync:")
    with cols[1]:
        if st.button("Re-read everything", icon=":material/cloud_download:",
                     width="stretch",
                     help="Reads every list in full and makes the portal match it. "
                          "Changes still waiting to be sent are kept."):
            with st.spinner("Reading every list…"):
                changed = sum(store.reconcile(t) for t in store.specs)
            audit.log("SharePoint re-read", "Settings", "SharePoint", cfg.site_url,
                      new_value=f"{changed} rows", user=user)
            st.success(f"Done: {changed:,} row(s) refreshed.", icon=":material/done:")
    with cols[2]:
        if st.button("Check the lists", icon=":material/fact_check:", width="stretch"):
            try:
                have = store.client.lists(refresh=True)
                missing = [s.list_name for s in store.specs.values()
                           if s.list_name not in have]
                missing += [lib for lib in (cfg.documents_library, cfg.reports_library)
                            if lib not in have]
                if missing:
                    st.error("Missing in SharePoint: " + ", ".join(missing)
                             + ". Run the provisioning step in docs/SHAREPOINT.md.",
                             icon=":material/error:")
                else:
                    st.success(f"All {len(store.specs)} lists and both libraries are "
                               "there.", icon=":material/check_circle:")
            except Exception as exc:
                st.error(f"SharePoint did not answer: {exc}", icon=":material/cloud_off:")

ui.section("Data backup")
if store is not None:
    st.caption("The records live in SharePoint, so they are covered by your Microsoft "
               "365 retention and backup. The portal's local file is only a cache "
               "that it rebuilds from SharePoint.")
elif user["role_name"] == "Super Admin":
    with open(db.DB_PATH, "rb") as fh:
        st.download_button("Download a copy of the database", fh.read(),
                           "rtps_qap_backup.db", "application/x-sqlite3",
                           icon=":material/backup:",
                           on_click=lambda: audit.log("Backup downloaded", "Settings",
                                                      "database", db.DB_PATH.name,
                                                      user=user))
else:
    st.caption("Only a Super Admin can download the database.")
