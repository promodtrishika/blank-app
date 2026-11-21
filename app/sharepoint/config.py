"""Where the SharePoint connection is configured.

Read from `.streamlit/secrets.toml` under `[sharepoint]`, or from RTPS_SP_*
environment variables when there is no secrets file (the provisioning CLI,
containers). The client secret is never written anywhere by the portal.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class SharePointConfig:
    tenant_id: str
    client_id: str
    client_secret: str
    site_hostname: str            # contoso.sharepoint.com
    site_path: str                # /sites/RTPS-QAP
    list_prefix: str = "RTPS_"
    documents_library: str = "RTPS Documents"
    reports_library: str = "RTPS Reports"
    graph_url: str = "https://graph.microsoft.com/v1.0"
    login_url: str = "https://login.microsoftonline.com"
    bootstrap_admin_email: str = ""
    pull_interval_seconds: int = 30
    cache_path: str = ""

    @property
    def site_url(self) -> str:
        return f"https://{self.site_hostname}{self.site_path}"


FIELDS = {
    "tenant_id": "TENANT_ID",
    "client_id": "CLIENT_ID",
    "client_secret": "CLIENT_SECRET",
    "site_hostname": "SITE_HOSTNAME",
    "site_path": "SITE_PATH",
    "list_prefix": "LIST_PREFIX",
    "documents_library": "DOCUMENTS_LIBRARY",
    "reports_library": "REPORTS_LIBRARY",
    "graph_url": "GRAPH_URL",
    "login_url": "LOGIN_URL",
    "bootstrap_admin_email": "BOOTSTRAP_ADMIN_EMAIL",
    "pull_interval_seconds": "PULL_INTERVAL_SECONDS",
    "cache_path": "CACHE_PATH",
}
REQUIRED = ("tenant_id", "client_id", "client_secret", "site_hostname", "site_path")


def _from_secrets() -> dict | None:
    try:
        import streamlit as st

        section = st.secrets.get("sharepoint")
    except Exception:  # no secrets file, or not running under Streamlit
        return None
    if not section:
        return None
    return {k: section.get(k) for k in [*FIELDS, "enabled"]}


def _from_env() -> dict | None:
    if os.environ.get("RTPS_SP_ENABLED", "").lower() not in ("1", "true", "yes"):
        return None
    values = {k: os.environ.get(f"RTPS_SP_{v}") for k, v in FIELDS.items()}
    values["enabled"] = True
    return values


def load() -> SharePointConfig | None:
    """The configuration, or None when SharePoint is not switched on."""
    raw = _from_env() or _from_secrets()
    if not raw or not raw.get("enabled"):
        return None
    missing = [k for k in REQUIRED if not raw.get(k)]
    if missing:
        raise ValueError("SharePoint is enabled but these settings are missing: "
                         + ", ".join(missing))
    values = {k: v for k, v in raw.items() if k in FIELDS and v not in (None, "")}
    if "pull_interval_seconds" in values:
        values["pull_interval_seconds"] = int(values["pull_interval_seconds"])
    values["site_path"] = "/" + values["site_path"].strip("/")
    for key in ("graph_url", "login_url"):
        if key in values:
            values[key] = values[key].rstrip("/")
    return SharePointConfig(**values)
