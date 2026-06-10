"""Spike: inspect raw xma_clip payload in the pending thread to find the reel reference."""
import json
import os

from dotenv import load_dotenv
from instagrapi import Client

load_dotenv()

cl = Client()
cl.load_settings("data/ig.session.json")
cl.login_by_sessionid(os.environ["IG_SESSIONID"])

result = cl.private_request("direct_v2/pending_inbox/", params={"limit": 5})
threads = result["inbox"]["threads"]
for t in threads:
    for item in t["items"]:
        item_type = item.get("item_type")
        keys = sorted(item.keys())
        print(f"item_type={item_type} keys={keys}")
        for k in ("xma_clip", "xma_media_share", "clip", "media_share"):
            if k in item:
                print(f"--- {k} payload ---")
                print(json.dumps(item[k], indent=2, default=str)[:3000])
