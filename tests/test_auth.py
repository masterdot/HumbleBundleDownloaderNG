import pytest

from hbdl import auth


def test_load_cookie_file_extracts_session_cookie(tmp_path):
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(
        "# Netscape HTTP Cookie File\n"
        ".humblebundle.com\tTRUE\t/\tTRUE\t2147483647\t_simpleauth_sess\tsecret-value\n"
    )
    value = auth._load_cookie_file(cookie_file)
    assert value == "secret-value"


def test_load_cookie_file_returns_none_without_session_cookie(tmp_path):
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(
        "# Netscape HTTP Cookie File\n"
        ".humblebundle.com\tTRUE\t/\tTRUE\t2147483647\tother_cookie\tsomevalue\n"
    )
    assert auth._load_cookie_file(cookie_file) is None


def test_resolve_session_raises_without_any_source(tmp_path, monkeypatch):
    monkeypatch.delenv("HBDL_COOKIE", raising=False)
    monkeypatch.delenv("HBDL_COOKIE_FILE", raising=False)
    monkeypatch.setattr(auth, "_load_saved_session", lambda path=None: None)
    monkeypatch.setattr(auth.config.Config, "load", classmethod(lambda cls, path=None: auth.config.Config()))

    with pytest.raises(auth.AuthError):
        auth.resolve_session()


def test_resolve_session_prefers_explicit_cookie_over_everything():
    session = auth.resolve_session(cookie="explicit-value")
    assert session.cookie_value == "explicit-value"
