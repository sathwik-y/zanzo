"""Instagram client construction: proxy wiring for egress IP control."""
from recall.config import Settings
from recall.instagram import client as client_mod


class _FakeClient:
    def __init__(self):
        self.user_id = "42"
        self.delay_range = None
        self.proxy = None

    def set_proxy(self, proxy):
        self.proxy = proxy

    def load_settings(self, path):
        pass

    def dump_settings(self, path):
        pass

    def login_by_sessionid(self, sessionid):
        return True


def _patch(monkeypatch, tmp_path, **over):
    fake = _FakeClient()
    monkeypatch.setattr(client_mod, "Client", lambda: fake)
    settings = Settings(
        ig_sessionid="42:abc:1:def",
        instagrapi_session_path=str(tmp_path / "ig.session.json"),
        **over,
    )
    monkeypatch.setattr(client_mod, "get_settings", lambda: settings)
    return fake


def test_build_client_applies_proxy_when_configured(monkeypatch, tmp_path):
    fake = _patch(monkeypatch, tmp_path, ig_proxy="http://user:pass@host:8080")
    client_mod.build_client()
    assert fake.proxy == "http://user:pass@host:8080"


def test_build_client_skips_proxy_when_unset(monkeypatch, tmp_path):
    fake = _patch(monkeypatch, tmp_path, ig_proxy="")
    client_mod.build_client()
    assert fake.proxy is None
