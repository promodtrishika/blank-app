"""Render every screen, as every demo role that can open it, and fail on any
exception — the check that the eighteen screens actually run."""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from app import auth

ROLES = ["superadmin", "stateadmin", "divadmin.patna", "distadmin.patna",
         "reviewer.patna", "verifier.patna", "operator.patna", "readonly"]


def session_user(username: str) -> dict:
    user = auth._load(username)
    user["permissions"] = auth.permissions(user["role_name"])
    return user


def cases():
    from app.navigation import PAGES

    for username in ROLES:
        user = session_user(username)
        for path, title, _icon, codes, _group in PAGES:
            if any(c in user["permissions"] for c in codes):
                yield pytest.param(username, path, id=f"{username}:{title}")


@pytest.mark.parametrize("username,path", list(cases()))
def test_screen_renders(username: str, path: str) -> None:
    at = AppTest.from_file(path, default_timeout=60)
    at.session_state["rtps_user"] = session_user(username)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.title, "every screen starts with its page title"


def test_login_screen_renders_and_signs_in() -> None:
    at = AppTest.from_file("streamlit_app.py", default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("RTPS QAP Portal" in t.value for t in at.title)
    at.text_input[0].input("operator.patna")
    at.text_input[1].input("Rtps@2026")
    at.text_input[2].input("123456")
    at.button[0].click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["rtps_user"]["role_name"] == "Operator"


def test_wrong_password_is_refused() -> None:
    at = AppTest.from_file("streamlit_app.py", default_timeout=60)
    at.run()
    at.text_input[0].input("operator.patna")
    at.text_input[1].input("not-the-password")
    at.text_input[2].input("123456")
    at.button[0].click().run()
    assert "rtps_user" not in at.session_state
    assert any("Wrong password" in e.value for e in at.error)


def test_role_without_permission_is_stopped() -> None:
    at = AppTest.from_file("app/views/users.py", default_timeout=60)
    at.session_state["rtps_user"] = session_user("operator.patna")
    at.run()
    assert any("cannot open this screen" in e.value for e in at.error)
