"""Spike: log into the burner account once, persist the session, fetch saved medias.

Session is saved to data/ig.session.json so we never log in twice.
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from instagrapi import Client

load_dotenv()

SESSION_PATH = Path("data/ig.session.json")
SESSION_PATH.parent.mkdir(exist_ok=True)

cl = Client()
cl.delay_range = [2, 5]  # human-ish pacing between requests

if SESSION_PATH.exists():
    print("Loading existing session/device settings...")
    cl.load_settings(SESSION_PATH)

session_id = os.environ.get("IG_SESSIONID")
try:
    if session_id:
        print("Login via sessionid cookie...")
        cl.login_by_sessionid(session_id)
    else:
        print("Login via username/password...")
        cl.login(os.environ["IG_USERNAME"], os.environ["IG_PASSWORD"])
finally:
    # Persist device identifiers even on challenge, so the retry after
    # manual approval presents the same device to Instagram.
    cl.dump_settings(SESSION_PATH)
    print(f"Settings persisted to {SESSION_PATH}")

me = cl.account_info()
print(f"LOGIN OK: user_id={cl.user_id} username={me.username}")

saved = cl.collection_medias("ALL_MEDIA_AUTO_COLLECTION", amount=20)
print(f"SAVED ITEMS: {len(saved)}")
for m in saved:
    print(f"  - pk={m.pk} type={m.media_type} product={m.product_type} caption={(m.caption_text or '')[:60]!r}")

# Also check DM inbox (second ingestion path)
threads = cl.direct_threads(amount=5)
print(f"DM THREADS: {len(threads)}")
for t in threads:
    last = t.messages[0] if t.messages else None
    print(f"  - thread={t.id} users={[u.username for u in t.users]} last_type={getattr(last, 'item_type', None)}")
