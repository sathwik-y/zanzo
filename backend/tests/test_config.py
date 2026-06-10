from recall.config import Settings


def test_settings_load_with_defaults():
    s = Settings(_env_file=None)
    assert s.queue_name == "recall:jobs"
    assert s.embedding_dimensions == 1536
    assert s.whisper_model_size == "small"


def test_settings_read_env(monkeypatch):
    monkeypatch.setenv("API_KEY", "sekrit")
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "60")
    s = Settings(_env_file=None)
    assert s.api_key == "sekrit"
    assert s.poll_interval_seconds == 60
