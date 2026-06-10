import json
from pathlib import Path

from recall.instagram.dms import _pk_from_target_url, parse_inbox_items

FIXTURE = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "pending_inbox.json").read_text()
)


def test_pk_from_target_url():
    url = "https://www.instagram.com/reel/DYz7y55zEon/?id=3905728284751317543_60605511491&is_sponsored=false"
    assert _pk_from_target_url(url) == "3905728284751317543"
    assert _pk_from_target_url("https://www.instagram.com/reel/x/?foo=bar") is None


def test_parse_inbox_items_xma_and_media_share():
    found = parse_inbox_items(FIXTURE["inbox"]["threads"])
    pks = [f.media_pk for f in found]
    # two xma reels + one classic media_share; text and the broken xma are skipped
    assert pks == ["3905728284751317543", "3907587204131736497", "3901112223334445556"]

    reel = found[0]
    assert reel.source == "DM"
    assert reel.media_type == "REEL"
    assert reel.instagram_url == "https://www.instagram.com/reel/DYz7y55zEon/"
    assert reel.saved_at is not None

    share = found[2]
    assert share.media_type == "POST"
    assert share.instagram_url == "https://www.instagram.com/p/DYabcdEFGH/"
