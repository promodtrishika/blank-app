"""Write .streamlit/secrets.toml from environment variables at startup.

Streamlit's Microsoft 365 sign-in (st.login) reads its settings only from
secrets.toml. On Azure App Service the settings live in App Settings, which
reach the app as environment variables, so `startup.sh` runs this first.

    RTPS_AUTH_CLIENT_ID       app registration's client id   (default: RTPS_SP_CLIENT_ID)
    RTPS_AUTH_CLIENT_SECRET   its client secret              (default: RTPS_SP_CLIENT_SECRET)
    RTPS_AUTH_TENANT_ID       directory (tenant) id          (default: RTPS_SP_TENANT_ID)
    RTPS_AUTH_REDIRECT_URI    https://<host>/oauth2callback  (default: from WEBSITE_HOSTNAME)
    RTPS_AUTH_COOKIE_SECRET   signs the sign-in cookie       (default: generated once, kept
                                                              in RTPS_DATA_DIR)
    RTPS_AUTH_METADATA_URL    OpenID metadata                (default: Microsoft's, for the tenant)

A secrets.toml someone wrote by hand is never overwritten: only a file this
script wrote (it carries a marker line) is replaced.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / ".streamlit" / "secrets.toml"
MARKER = "# Written by app/deploy_secrets.py from environment variables. Do not edit."


def _env(name: str, fallback: str | None = None) -> str | None:
    """The variable's value, else the fallback variable's, else None."""
    for key in (name, fallback):
        if key and os.environ.get(key, "").strip():
            return os.environ[key].strip()
    return None


def _cookie_secret() -> str:
    given = _env("RTPS_AUTH_COOKIE_SECRET")
    if given:
        return given
    # Kept on persistent storage so a restart does not sign everyone out.
    data_dir = Path(os.environ.get("RTPS_DATA_DIR", ROOT / ".rtps_cache"))
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "cookie_secret"
    if path.exists() and path.read_text().strip():
        return path.read_text().strip()
    value = secrets.token_urlsafe(48)
    path.write_text(value)
    path.chmod(0o600)
    return value


def build() -> str | None:
    """The secrets.toml text, or None when sign-in is not configured."""
    client_id = _env("RTPS_AUTH_CLIENT_ID", "RTPS_SP_CLIENT_ID")
    client_secret = _env("RTPS_AUTH_CLIENT_SECRET", "RTPS_SP_CLIENT_SECRET")
    tenant = _env("RTPS_AUTH_TENANT_ID", "RTPS_SP_TENANT_ID")
    if not (client_id and client_secret and tenant):
        return None
    redirect = _env("RTPS_AUTH_REDIRECT_URI")
    if not redirect:
        host = os.environ.get("WEBSITE_HOSTNAME")
        if not host:
            raise SystemExit("RTPS_AUTH_REDIRECT_URI is not set and WEBSITE_HOSTNAME is "
                             "not available to derive it from.")
        redirect = f"https://{host}/oauth2callback"
    metadata = _env("RTPS_AUTH_METADATA_URL") or (
        f"https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration")
    q = json.dumps                     # a JSON string is a valid TOML basic string
    return "\n".join([
        MARKER,
        "",
        "[auth]",
        f"redirect_uri = {q(redirect)}",
        f"cookie_secret = {q(_cookie_secret())}",
        "",
        "[auth.microsoft]",
        f"client_id = {q(client_id)}",
        f"client_secret = {q(client_secret)}",
        f"server_metadata_url = {q(metadata)}",
        "",
    ])


def main() -> int:
    text = build()
    if text is None:
        print("deploy_secrets: Microsoft 365 sign-in is not configured "
              "(no RTPS_AUTH_* / RTPS_SP_* client settings); leaving secrets.toml alone.")
        return 0
    if TARGET.exists() and not TARGET.read_text().startswith(MARKER):
        print(f"deploy_secrets: {TARGET} was written by hand; not overwriting it.")
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(text)
    TARGET.chmod(0o600)
    print(f"deploy_secrets: wrote {TARGET} (sign-in redirect "
          f"{text.split('redirect_uri = ')[1].splitlines()[0]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
