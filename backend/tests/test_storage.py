import pytest

from recall.storage import LocalDirStorage, S3Storage


def test_local_dir_storage(tmp_path):
    s = LocalDirStorage(tmp_path / "store")
    src = tmp_path / "x.bin"
    src.write_bytes(b"hello")
    assert s.put_file(src, "media/1/x.bin") == 5
    assert s.exists("media/1/x.bin")
    dest = tmp_path / "out.bin"
    s.get_to_file("media/1/x.bin", dest)
    assert dest.read_bytes() == b"hello"
    assert not s.exists("media/1/missing.bin")


def test_s3_storage_round_trip(tmp_path):
    try:
        s = S3Storage()
    except Exception:
        pytest.skip("minio not running (docker compose up -d minio)")
    key = "test/round-trip.bin"
    assert s.put_bytes(b"recall", key, "application/octet-stream") == 6
    assert s.exists(key)
    dest = tmp_path / "out.bin"
    s.get_to_file(key, dest)
    assert dest.read_bytes() == b"recall"
    url = s.presigned_url(key)
    assert "test/round-trip.bin" in url and "X-Amz-Signature" in url
