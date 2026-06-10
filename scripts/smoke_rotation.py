from dotenv import load_dotenv

load_dotenv()

from recall.ai.gemini import GeminiClient  # noqa: E402
from recall.db import get_session_factory  # noqa: E402

g = GeminiClient()
print("clients in pool:", len(g._clients))
db = get_session_factory()()
for n in range(3):
    r = g.classify(db, None, "Comment GMB to get the local SEO workflow", None)
    print(f"call {n + 1}: category={r['category']} (rr cursor now {g._rr})")
v = g.embed(db, None, "tokyo ramen travel guide")
print("embed dims:", len(v))
