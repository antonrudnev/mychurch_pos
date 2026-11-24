import html
import json
import logging
import random
import re
from datetime import date, datetime, time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

TOKEN_CACHE_KEY = "azbyka:api:jwt_token"

TEXT_TYPE_TITLES: dict[int, str] = {
    1: "Чтения Св. Писания",
    2: "Богослужебные указания",
    3: "Цитата дня",
    4: "Мысли св. Феофана Затворника",
    5: "Притча дня",
    6: "Проповедь дня",
    7: "День в истории Церкви",
    8: "Книги и статьи дня",
    9: "Вопрос священнику",
    10: "Важная информация",
    11: "Аудиокниги и фильмы",
    12: "Основы православия",
}
ALLOWED_TEXT_TYPES: frozenset[int] = frozenset({1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12})


def _base_url() -> str:
    return settings.AZBYKA_API_BASE_URL.rstrip("/")


def _request(path: str, payload: dict[str, Any] | None = None, token: str | None = None) -> dict[str, Any]:
    headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        headers["Content-Type"] = "application/json"

    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = Request(f"{_base_url()}{path}", data=data, headers=headers, method="POST" if payload else "GET")
    with urlopen(req, timeout=4) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_token(refresh: bool = False) -> str | None:
    email, password = getattr(settings, "AZBYKA_API_EMAIL", ""), getattr(settings, "AZBYKA_API_PASSWORD", "")
    if not (email and password):
        return None

    cached: str | None = cache.get(TOKEN_CACHE_KEY)
    if cached and not refresh:
        return cached

    attempts = [("/api-v2/token/refresh", {"token": cached})] if (cached and refresh) else []
    attempts.append(("/api-v2/login", {"email": email, "password": password}))

    for path, body in attempts:
        try:
            if token := _request(path, payload=body).get("token"):
                cache.set(TOKEN_CACHE_KEY, token, timeout=60 * 60 * 24 * 25)
                return token
        except Exception as exc:
            logger.debug("Azbyka auth failed (%s): %s", path, exc)
    return None


def _api_get(path: str) -> dict[str, Any] | None:
    if not (token := _get_token()):
        return None
    try:
        return _request(path, token=token)
    except HTTPError as exc:
        if exc.code == 401 and (new_token := _get_token(refresh=True)):
            try:
                return _request(path, token=new_token)
            except Exception as retry_exc:
                logger.warning("Azbyka retry failed for %s: %s", path, retry_exc)
    except Exception as exc:
        logger.warning("Azbyka request failed for %s: %s", path, exc)
    return None


def _clean_html(raw: str) -> str:
    text = re.sub(r"<br\s*/?>|\s*</p>\s*<p[^>]*>\s*", "\n", raw, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _pick_daily_text(texts: list[dict[str, Any]]) -> dict[str, str] | None:
    candidates = [t for t in texts if t.get("type") in ALLOWED_TEXT_TYPES and t.get("id")]
    random.shuffle(candidates)

    for meta in candidates:
        data = _api_get(f"/api-v2/additional-calendar-texts/{meta['id']}") or {}
        if clean := _clean_html(data.get("text") or ""):
            title = (data.get("title") or meta.get("title") or TEXT_TYPE_TITLES.get(meta["type"], "Слово дня")).strip()
            return {"title": title, "text": clean}
    return None


def get_today_calendar_widget(target_date: date | None = None) -> dict[str, Any] | None:
    now = timezone.localtime()
    date_str = (target_date or now.date()).strftime("%Y-%m-%d")
    cache_key = f"azbyka:widget:{date_str}"

    if (cached := cache.get(cache_key)) is not None:
        return cached or None

    day_direct = _api_get(f"/api-v2/day-direct/{date_str}")
    daily_text = _pick_daily_text(day_direct.get("texts", [])) if day_direct else None

    if not daily_text:
        cache.set(cache_key, False, timeout=300)
        return None

    midnight = timezone.make_aware(datetime.combine(now.date(), time.max), now.tzinfo)
    ttl =  min(60 * 60 * 4, max(60, int((midnight - now).total_seconds())))

    widget_data = {
        "date_str": date_str,
        "source_url": f"{_base_url()}/{date_str}",
        "parable": daily_text,
    }
    cache.set(cache_key, widget_data, timeout=ttl)
    return widget_data
