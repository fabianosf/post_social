"""
Meta Conversions API (CAPI) — server-side event tracking.
Fires asynchronously to avoid blocking request/response cycle.
"""

import hashlib
import logging
import os
import threading
import uuid
from datetime import datetime, timezone

import requests as _req

logger = logging.getLogger(__name__)

_PIXEL_ID = os.environ.get("META_PIXEL_ID", "")
_TOKEN    = os.environ.get("META_CAPI_TOKEN", "")
_URL      = "https://graph.facebook.com/v19.0/{pixel_id}/events"
_TEST_CODE = os.environ.get("META_CAPI_TEST_CODE", "")  # optional, for Events Manager testing


def _hash(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()


def _send(payload: dict) -> None:
    if _TEST_CODE:
        payload["test_event_code"] = _TEST_CODE
    try:
        resp = _req.post(_URL.format(pixel_id=_PIXEL_ID), json=payload, timeout=8)
        if resp.status_code != 200:
            logger.warning("Meta CAPI %s: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.warning("Meta CAPI error: %s", exc)


def send_event(
    event_name: str,
    *,
    email: str = "",
    ip: str = "",
    user_agent: str = "",
    event_id: str = "",
    event_source_url: str = "",
    fbc: str = "",
    fbp: str = "",
) -> str:
    """Fire a CAPI event asynchronously. Returns the event_id used."""
    if not _PIXEL_ID or not _TOKEN:
        return ""

    eid = event_id or str(uuid.uuid4())

    user_data: dict = {
        "client_ip_address": ip,
        "client_user_agent": user_agent,
    }
    if email:
        user_data["em"] = [_hash(email)]
    if fbc:
        user_data["fbc"] = fbc
    if fbp:
        user_data["fbp"] = fbp

    payload = {
        "access_token": _TOKEN,
        "data": [{
            "event_name":       event_name,
            "event_time":       int(datetime.now(timezone.utc).timestamp()),
            "event_id":         eid,
            "action_source":    "website",
            "event_source_url": event_source_url,
            "user_data":        user_data,
        }],
    }

    threading.Thread(target=_send, args=(payload,), daemon=True).start()
    return eid
