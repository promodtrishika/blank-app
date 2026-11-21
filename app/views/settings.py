"""Screen 16 — Settings (blueprint section 6, security framework)."""

from __future__ import annotations

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
    with row[1]:
        min_len = st.number_input("Minimum password length", 8, 32,
                                  int(val("password_min_length")))
    with row[2]:
        mfa = st.toggle("Ask for a one-time passcode at sign-in",
                        val("mfa_required") == "1")

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
        {"Control": "Authentication", "Prototype": "Username + salted SHA-256 hash",
         "Production": "Azure AD SSO with JWT"},
        {"Control": "Multi-factor", "Prototype": "Six-digit passcode field (stubbed)",
         "Production": "Azure AD MFA"},
        {"Control": "Authorisation", "Prototype": "Role → permission matrix + data scope",
         "Production": "Same model, enforced in the .NET API"},
        {"Control": "Session timeout", "Prototype": "Idle timer from this page",
         "Production": "Token lifetime + idle timeout"},
        {"Control": "Audit logging", "Prototype": "Every write via one helper",
         "Production": "Same, to tblAuditLogs in SQL Server"},
        {"Control": "Transport", "Prototype": "Whatever serves Streamlit",
         "Production": "HTTPS only, HSTS"},
        {"Control": "Backup", "Prototype": "Download the SQLite file below",
         "Production": "SQL Server scheduled backup + DR replica"},
    ],
    hide_index=True, width="stretch")

ui.section("Data backup")
if user["role_name"] == "Super Admin":
    with open(db.DB_PATH, "rb") as fh:
        st.download_button("Download a copy of the database", fh.read(),
                           "rtps_qap_backup.db", "application/x-sqlite3",
                           icon=":material/backup:",
                           on_click=lambda: audit.log("Backup downloaded", "Settings",
                                                      "database", db.DB_PATH.name,
                                                      user=user))
else:
    st.caption("Only a Super Admin can download the database.")
