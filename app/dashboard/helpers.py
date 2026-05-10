"""
Helpers compartilhados do dashboard: limites, slots, watermark.
"""

import json
import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from PIL import Image

from ..models import db, InstagramAccount, PostQueue

BRAZIL_TZ = ZoneInfo("America/Sao_Paulo")

SAFE_LIMITS = {
    "max_posts_per_day": 3,
    "max_stories_per_day": 4,
    "min_interval_minutes": 240,
    "random_delay_minutes": 20,
    "safe_hours_start": 8,
    "safe_hours_end": 22,
    "suggested_times": [9, 17],
}

ALLOWED_IMG = {"jpg", "jpeg", "png", "webp"}
ALLOWED_VID = {"mp4", "mov"}
ALLOWED_ALL = ALLOWED_IMG | ALLOWED_VID


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_ALL


def is_video(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_VID


def get_account_slots(account_id: int) -> tuple[list[str], list[str]]:
    acc = InstagramAccount.query.get(account_id)
    defaults_wd = ["09:00", "17:00"]
    defaults_we = ["10:30", "16:00"]
    if not acc:
        return defaults_wd, defaults_we
    try:
        wd = json.loads(acc.weekday_slots or "[]") or defaults_wd
    except Exception:
        wd = defaults_wd
    try:
        we = json.loads(acc.weekend_slots or "[]") or defaults_we
    except Exception:
        we = defaults_we
    return wd, we


def next_free_slot(account_id: int, after: datetime) -> datetime:
    """Retorna o próximo slot livre (UTC naive) para a conta."""
    MAX_DAY = SAFE_LIMITS["max_posts_per_day"]
    weekday_slots, weekend_slots = get_account_slots(account_id)

    after_br = after.replace(tzinfo=timezone.utc).astimezone(BRAZIL_TZ)

    occupied = {
        p.scheduled_at for p in PostQueue.query.filter(
            PostQueue.account_id == account_id,
            PostQueue.status == "pending",
            PostQueue.scheduled_at.isnot(None),
        ).all()
        if p.scheduled_at
    }

    for day_offset in range(14):
        candidate_day_br = (after_br + timedelta(days=day_offset)).date()
        weekday = candidate_day_br.weekday()
        slots = weekday_slots if weekday < 5 else weekend_slots

        day_start_utc = datetime(candidate_day_br.year, candidate_day_br.month, candidate_day_br.day,
                                 0, 0, 0, tzinfo=BRAZIL_TZ).astimezone(timezone.utc).replace(tzinfo=None)
        day_end_utc = day_start_utc + timedelta(days=1)
        posts_day = PostQueue.query.filter(
            PostQueue.account_id == account_id,
            PostQueue.post_type != "story",
            PostQueue.status.in_(["pending", "posted", "processing"]),
            db.or_(
                db.and_(PostQueue.scheduled_at >= day_start_utc, PostQueue.scheduled_at < day_end_utc),
                db.and_(PostQueue.posted_at >= day_start_utc, PostQueue.posted_at < day_end_utc),
            ),
        ).count()

        if posts_day >= MAX_DAY:
            continue

        for slot_str in slots:
            h, m = map(int, slot_str.split(":"))
            slot_br = datetime(candidate_day_br.year, candidate_day_br.month, candidate_day_br.day,
                               h, m, 0, tzinfo=BRAZIL_TZ)
            slot_utc = slot_br.astimezone(timezone.utc).replace(tzinfo=None)
            if slot_utc <= after + timedelta(minutes=5):
                continue
            if slot_utc in occupied:
                continue
            return slot_utc

        safe_start = SAFE_LIMITS.get("safe_hours_start", 8)
        safe_end = SAFE_LIMITS.get("safe_hours_end", 22)
        for try_h in range(safe_start, safe_end):
            for try_m in (0, 30):
                slot_br = datetime(
                    candidate_day_br.year, candidate_day_br.month, candidate_day_br.day,
                    try_h, try_m, 0, tzinfo=BRAZIL_TZ,
                )
                slot_utc = slot_br.astimezone(timezone.utc).replace(tzinfo=None)
                if slot_utc <= after + timedelta(minutes=5):
                    continue
                if slot_utc in occupied:
                    continue
                return slot_utc

    fallback_br = (after_br + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    return fallback_br.astimezone(timezone.utc).replace(tzinfo=None)


def auto_schedule_posts(posts_to_schedule: list, account_id: int, client_id: int,
                        start_time: datetime | None = None) -> int:
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    search_after = start_time if start_time else now_utc
    scheduled = 0

    for post in posts_to_schedule:
        slot = next_free_slot(account_id, search_after)
        post.scheduled_at = slot
        scheduled += 1
        search_after = slot

    return scheduled


def apply_watermark(image_path: str, watermark_path: str, position: str, opacity: int) -> str:
    try:
        base = Image.open(image_path).convert("RGBA")
        wm = Image.open(watermark_path).convert("RGBA")

        wm_width = int(base.width * 0.2)
        wm_ratio = wm_width / wm.width
        wm_height = int(wm.height * wm_ratio)
        wm = wm.resize((wm_width, wm_height), Image.LANCZOS)

        alpha = wm.split()[3]
        alpha = alpha.point(lambda p: int(p * opacity / 100))
        wm.putalpha(alpha)

        margin = 20
        positions = {
            "top-left": (margin, margin),
            "top-right": (base.width - wm_width - margin, margin),
            "bottom-left": (margin, base.height - wm_height - margin),
            "bottom-right": (base.width - wm_width - margin, base.height - wm_height - margin),
            "center": ((base.width - wm_width) // 2, (base.height - wm_height) // 2),
        }
        pos = positions.get(position, positions["bottom-right"])

        base.paste(wm, pos, wm)
        base = base.convert("RGB")
        base.save(image_path, quality=95)
        return image_path
    except Exception:
        return image_path
