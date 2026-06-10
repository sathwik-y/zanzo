from recall.pipeline.runner import process_item


def test_happy_path_walks_all_stages(db, make_item):
    item = make_item()
    calls = []

    def stage(name):
        def _s(db_, it):
            calls.append((name, it.status))
        return _s

    stages = {n: stage(n) for n in ["fetch", "transcribe", "classify", "extract", "embed"]}
    assert process_item(db, str(item.id), stages) is True
    # each stage saw its own running status
    assert calls == [
        ("fetch", "FETCHING"),
        ("transcribe", "TRANSCRIBING"),
        ("classify", "CLASSIFYING"),
        ("extract", "EXTRACTING"),
        ("embed", "EMBEDDING"),
    ]
    db.refresh(item)
    assert item.status == "COMPLETED"
    assert item.error_log is None


def test_failure_parks_item_with_error_log(db, make_item):
    item = make_item()

    def boom(db_, it):
        raise ValueError("no audio track")

    stages = {"fetch": lambda d, i: None, "transcribe": boom}
    assert process_item(db, str(item.id), stages) is False
    db.refresh(item)
    assert item.status == "FAILED_TRANSCRIBE"
    assert item.error_log["stage"] == "transcribe"
    assert "no audio track" in item.error_log["error"]


def test_retry_after_failure_completes(db, make_item):
    item = make_item()
    attempts = {"n": 0}

    def flaky(db_, it):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("transient")

    stages = {"fetch": flaky}
    assert process_item(db, str(item.id), stages) is False
    assert process_item(db, str(item.id), stages) is True
    db.refresh(item)
    assert item.status == "COMPLETED"
    assert item.error_log is None


def test_missing_item_returns_false(db):
    assert process_item(db, "00000000-0000-0000-0000-000000000000", {}) is False
