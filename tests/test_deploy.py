"""The Azure App Service startup pieces: secrets.toml from App Settings."""

from __future__ import annotations

import tomllib

import pytest

from app import deploy_secrets


@pytest.fixture
def target(tmp_path, monkeypatch):
    path = tmp_path / ".streamlit" / "secrets.toml"
    monkeypatch.setattr(deploy_secrets, "TARGET", path)
    monkeypatch.setenv("RTPS_DATA_DIR", str(tmp_path / "data"))
    for name in ("RTPS_AUTH_CLIENT_ID", "RTPS_AUTH_CLIENT_SECRET", "RTPS_AUTH_TENANT_ID",
                 "RTPS_AUTH_REDIRECT_URI", "RTPS_AUTH_COOKIE_SECRET", "RTPS_AUTH_METADATA_URL",
                 "RTPS_SP_CLIENT_ID", "RTPS_SP_CLIENT_SECRET", "RTPS_SP_TENANT_ID",
                 "WEBSITE_HOSTNAME"):
        monkeypatch.delenv(name, raising=False)
    return path


def test_nothing_is_written_without_sign_in_settings(target):
    assert deploy_secrets.main() == 0
    assert not target.exists()


def test_defaults_come_from_the_sharepoint_registration_and_the_host(target, monkeypatch):
    monkeypatch.setenv("RTPS_SP_CLIENT_ID", "cid")
    monkeypatch.setenv("RTPS_SP_CLIENT_SECRET", 'se"cr\\et')       # quoting survives
    monkeypatch.setenv("RTPS_SP_TENANT_ID", "tid")
    monkeypatch.setenv("WEBSITE_HOSTNAME", "rtps-qap.azurewebsites.net")
    deploy_secrets.main()
    cfg = tomllib.loads(target.read_text())
    assert cfg["auth"]["redirect_uri"] == "https://rtps-qap.azurewebsites.net/oauth2callback"
    assert cfg["auth"]["microsoft"]["client_id"] == "cid"
    assert cfg["auth"]["microsoft"]["client_secret"] == 'se"cr\\et'
    assert cfg["auth"]["microsoft"]["server_metadata_url"] == (
        "https://login.microsoftonline.com/tid/v2.0/.well-known/openid-configuration")
    assert oct(target.stat().st_mode & 0o777) == "0o600"


def test_cookie_secret_is_kept_across_restarts(target, monkeypatch):
    for k, v in {"RTPS_AUTH_CLIENT_ID": "c", "RTPS_AUTH_CLIENT_SECRET": "s",
                 "RTPS_AUTH_TENANT_ID": "t",
                 "RTPS_AUTH_REDIRECT_URI": "http://localhost:8501/oauth2callback"}.items():
        monkeypatch.setenv(k, v)
    deploy_secrets.main()
    first = tomllib.loads(target.read_text())["auth"]["cookie_secret"]
    target.unlink()
    deploy_secrets.main()
    assert tomllib.loads(target.read_text())["auth"]["cookie_secret"] == first
    assert len(first) >= 40


def test_a_hand_written_secrets_file_is_left_alone(target, monkeypatch):
    target.parent.mkdir(parents=True)
    target.write_text('[sharepoint]\nenabled = true\n')
    for k, v in {"RTPS_AUTH_CLIENT_ID": "c", "RTPS_AUTH_CLIENT_SECRET": "s",
                 "RTPS_AUTH_TENANT_ID": "t", "WEBSITE_HOSTNAME": "x.azurewebsites.net"}.items():
        monkeypatch.setenv(k, v)
    deploy_secrets.main()
    assert target.read_text() == '[sharepoint]\nenabled = true\n'


def test_missing_redirect_and_host_is_a_clear_error(target, monkeypatch):
    for k, v in {"RTPS_AUTH_CLIENT_ID": "c", "RTPS_AUTH_CLIENT_SECRET": "s",
                 "RTPS_AUTH_TENANT_ID": "t"}.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(SystemExit, match="RTPS_AUTH_REDIRECT_URI"):
        deploy_secrets.main()


# --- the Teams app package -------------------------------------------------

import io
import json
import zipfile

from PIL import Image
from streamlit.testing.v1 import AppTest

from app import teams_package


def test_teams_package_has_a_manifest_and_both_icons(tmp_path):
    out = teams_package.build("https://rtps-qap.azurewebsites.net/", tmp_path / "t.zip",
                              "RTPS QAP Portal", "RTPS Cell")
    z = zipfile.ZipFile(out)
    assert sorted(z.namelist()) == ["color.png", "manifest.json", "outline.png"]
    m = json.loads(z.read("manifest.json"))
    tab = m["staticTabs"][0]
    assert tab["contentUrl"] == "https://rtps-qap.azurewebsites.net/?from=teams"
    assert m["validDomains"] == ["rtps-qap.azurewebsites.net"]
    assert len(m["name"]["short"]) <= 30 and len(m["description"]["short"]) <= 80
    assert Image.open(io.BytesIO(z.read("color.png"))).size == (192, 192)
    outline = Image.open(io.BytesIO(z.read("outline.png"))).convert("RGBA")
    assert outline.size == (32, 32)
    assert outline.getpixel((0, 0))[3] == 0               # transparent background


def test_teams_app_id_is_stable_for_one_address():
    a = teams_package.manifest("https://rtps-qap.azurewebsites.net")["id"]
    b = teams_package.manifest("https://rtps-qap.azurewebsites.net/")["id"]
    c = teams_package.manifest("https://other.azurewebsites.net")["id"]
    assert a == b != c


def test_teams_package_refuses_plain_http():
    with pytest.raises(ValueError, match="https"):
        teams_package.manifest("http://localhost:8501")


def test_teams_launcher_page_opens_the_portal_in_the_browser(monkeypatch):
    monkeypatch.setenv("WEBSITE_HOSTNAME", "rtps-qap.azurewebsites.net")
    monkeypatch.delenv("RTPS_PUBLIC_URL", raising=False)
    at = AppTest.from_file("streamlit_app.py", default_timeout=60)
    at.query_params["from"] = "teams"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert not at.text_input, "no sign-in form inside Teams"
    buttons = at.get("link_button")
    assert buttons and buttons[0].proto.url == "https://rtps-qap.azurewebsites.net"
