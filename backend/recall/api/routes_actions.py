"""Actions on extractions. V1: add an EVENT to your calendar via .ics download."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from recall.api.deps import AuthContext, get_auth, get_db, scoped_items
from recall.models import SavedItem

router = APIRouter(prefix="/actions", tags=["actions"])


@router.post("/event/{item_id}/add-to-calendar")
def event_to_ics(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth),
):
    item = db.scalar(scoped_items(select(SavedItem).where(SavedItem.id == item_id), auth))
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    if item.category != "EVENT" or item.extraction is None:
        raise HTTPException(status_code=422, detail="item is not an extracted EVENT")

    payload = item.extraction.payload
    if not payload.get("starts_at"):
        raise HTTPException(
            status_code=422,
            detail="no start datetime was extracted; edit the item or check the original post",
        )

    from ics import Calendar, Event

    event = Event()
    event.name = payload.get("title") or "Saved event"
    event.begin = payload["starts_at"]
    if payload.get("ends_at"):
        event.end = payload["ends_at"]
    location_bits = [payload.get("venue_name"), payload.get("venue_address"), payload.get("city")]
    location = ", ".join(b for b in location_bits if b)
    if location:
        event.location = location
    description = [payload.get("summary") or ""]
    for key in ("rsvp_url", "ticket_url", "price_info"):
        if payload.get(key):
            description.append(f"{key.replace('_', ' ')}: {payload[key]}")
    if item.instagram_url:
        description.append(f"Saved from: {item.instagram_url}")
    event.description = "\n".join(description)

    cal = Calendar()
    cal.events.add(event)

    filename = (payload.get("title") or "event").lower().replace(" ", "-")[:40] + ".ics"
    return Response(
        content=cal.serialize(),
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
