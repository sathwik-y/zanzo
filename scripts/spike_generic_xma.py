"""Inspect the raw generic_xma DM payload from helloveeru to find the resource URL."""
import json

from dotenv import load_dotenv

load_dotenv()

from recall.instagram.client import build_client  # noqa: E402

cl = build_client()
uid = cl.user_id_from_username("helloveeru")
t = cl.direct_thread_by_participants([int(uid)])
tid = t["thread"]["thread_id"]

res = cl.private_request(f"direct_v2/threads/{tid}/", params={"limit": 10})
items = res["thread"]["items"]
for it in items:
    itype = it.get("item_type")
    print("=== item_type:", itype, "| keys:", sorted(it.keys()))
    for k in ("generic_xma", "xma_generic", "link", "clip", "xma_clip", "raven_media", "media_share"):
        if k in it:
            print(f"--- {k} ---")
            print(json.dumps(it[k], indent=1, default=str)[:2500])
