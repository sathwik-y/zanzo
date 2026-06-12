"""Instagram client construction with session reuse.

Login strategy (in order of reliability, learned the hard way):
1. Reuse the persisted session file if present.
2. login_by_sessionid with the IG_SESSIONID cookie (skips checkpoint flows).
3. Username/password as last resort (often hits ChallengeRequired on new devices).

The session file is ALWAYS dumped after a login attempt so device identifiers
stay stable across restarts; Instagram treats a changing device as suspicious.
"""
import logging
from pathlib import Path

from instagrapi import Client
from instagrapi.exceptions import ChallengeRequired, LoginRequired

from recall.config import get_settings

logger = logging.getLogger(__name__)


class InstagramChallengeError(Exception):
    """Instagram requires manual verification; surface to the dashboard."""


def media_type_label(media_type: int, product_type: str | None) -> str:
    if media_type == 8:
        return "CAROUSEL"
    if media_type == 2:
        return "IGTV" if product_type == "igtv" else "REEL"
    return "POST"


def build_client() -> Client:
    settings = get_settings()
    session_path = Path(settings.instagrapi_session_path)
    session_path.parent.mkdir(parents=True, exist_ok=True)

    cl = Client()
    cl.delay_range = [2, 5]  # human-ish pacing between consecutive requests
    if settings.ig_proxy:
        cl.set_proxy(settings.ig_proxy)

    if session_path.exists():
        cl.load_settings(session_path)

    try:
        if settings.ig_sessionid:
            cl.login_by_sessionid(settings.ig_sessionid)
        elif settings.ig_username and settings.ig_password:
            cl.login(settings.ig_username, settings.ig_password)
        else:
            raise InstagramChallengeError(
                "No Instagram credentials configured (IG_SESSIONID or IG_USERNAME/IG_PASSWORD)"
            )
    except (ChallengeRequired, LoginRequired) as exc:
        raise InstagramChallengeError(str(exc)) from exc
    finally:
        try:
            cl.dump_settings(session_path)
        except Exception:  # never let settings persistence mask the real error
            logger.exception("failed to persist instagram session settings")

    logger.info("instagram login ok (user_id=%s)", cl.user_id)
    return cl


def build_client_for_bot(username: str, sessionid: str) -> Client:
    """Client for a pooled bot account; each bot keeps its own device file so
    Instagram sees a stable device per account."""
    settings = get_settings()
    base = Path(settings.instagrapi_session_path)
    session_path = base.with_name(f"ig.session.{username}.json")
    session_path.parent.mkdir(parents=True, exist_ok=True)

    cl = Client()
    cl.delay_range = [2, 5]
    if settings.ig_proxy:
        cl.set_proxy(settings.ig_proxy)
    if session_path.exists():
        cl.load_settings(session_path)
    try:
        cl.login_by_sessionid(sessionid)
    except (ChallengeRequired, LoginRequired) as exc:
        raise InstagramChallengeError(str(exc)) from exc
    finally:
        try:
            cl.dump_settings(session_path)
        except Exception:
            logger.exception("failed to persist session settings for bot %s", username)

    logger.info("instagram login ok for bot %s (user_id=%s)", username, cl.user_id)
    return cl
