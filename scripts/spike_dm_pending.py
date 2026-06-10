"""Spike: check the pending DM inbox for shared reels."""
import os

from dotenv import load_dotenv
from instagrapi import Client

load_dotenv()

cl = Client()
cl.load_settings("data/ig.session.json")
cl.login_by_sessionid(os.environ["IG_SESSIONID"])

pending = cl.direct_pending_inbox(amount=10)
print(f"PENDING THREADS: {len(pending)}")
for t in pending:
    print(f"thread={t.id} users={[u.username for u in t.users]}")
    for msg in t.messages:
        media_pk = None
        if msg.clip:
            media_pk = msg.clip.pk
        elif msg.media_share:
            media_pk = msg.media_share.pk
        print(f"  item_type={msg.item_type} media_pk={media_pk}")
