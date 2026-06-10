from sqlalchemy import select

from recall.db import get_session_factory
from recall.models import Engagement, Extraction, SavedItem

db = get_session_factory()()
print(f"{'author':16} {'status':18} {'category':14} {'extr':5} {'engagement'}")
print("-" * 78)
for i in db.scalars(select(SavedItem).order_by(SavedItem.ingested_at)):
    extr = db.scalar(select(Extraction).where(Extraction.item_id == i.id))
    eng = db.scalar(select(Engagement).where(Engagement.item_id == i.id))
    author = (i.author_username or "?")[:15]
    cat = (i.category or "-")[:13]
    print(f"{author:16} {i.status:18} {cat:14} {'yes' if extr else 'no':5} {eng.status if eng else '-'}")
