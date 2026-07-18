"""Synchronous client and payload helpers for the official FC Online API."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

DIVISION_METADATA_URL = (
    "https://static.api.nexon.co.kr/fifaonline4/latest/division.json"
)
MATCH_TYPE_1V1 = 50
MATCH_TYPE_2V2 = 52


class FcOnlineApiError(Exception):
    """A sanitized error suitable for translating into an HTTP response."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


@dataclass(frozen=True)
class DivisionValue:
    division_id: int | None
    division_name: str | None
    division_rank: int | None


@dataclass(frozen=True)
class FcOnlineSyncPayload:
    nickname: str
    ouid: str
    level: int | None
    division_1v1: DivisionValue
    division_2v2: DivisionValue


_client = httpx.Client(
    timeout=15.0,
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
)


def _api_base_url() -> str:
    configured = getattr(
        settings,
        "fc_online_api_base_url",
        "https://open.api.nexon.com/fconline/v1",
    )
    return str(configured).rstrip("/")


def _request_timeout() -> float:
    return float(getattr(settings, "fc_online_request_timeout_seconds", 15.0))


def _headers() -> dict[str, str]:
    key = str(getattr(settings, "nexon_api_key", "") or "").strip()
    if not key:
        raise FcOnlineApiError(
            "FC Online API key is not configured.",
            status_code=503,
        )
    return {"x-nxopen-api-key": key}


def _retry_after_seconds(response: httpx.Response) -> int | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0, int(value))
    except ValueError:
        return None


def _request_json(path: str, *, params: dict[str, Any] | None = None) -> object:
    """Call an authenticated endpoint without exposing keys or response bodies."""

    response: httpx.Response | None = None
    url = f"{_api_base_url()}/{path.lstrip('/')}"
    for attempt in range(2):
        try:
            response = _client.get(
                url,
                params=params,
                headers=_headers(),
                timeout=_request_timeout(),
            )
        except httpx.TimeoutException as exc:
            if attempt == 0:
                continue
            logger.warning("FC Online API request timed out")
            raise FcOnlineApiError(
                "FC Online API request timed out.",
                status_code=504,
            ) from exc
        except httpx.RequestError as exc:
            if attempt == 0:
                time.sleep(0.25)
                continue
            logger.warning("FC Online API network request failed")
            raise FcOnlineApiError(
                "FC Online API is temporarily unavailable.",
                status_code=502,
            ) from exc

        retry_after = _retry_after_seconds(response)
        if response.status_code in (429, 502, 503, 504) and attempt == 0:
            delay = retry_after if retry_after is not None else 0.25
            if delay <= 2:
                time.sleep(delay)
                continue
        break

    if response is None:
        raise FcOnlineApiError(
            "FC Online API did not return a response.",
            status_code=502,
        )
    if response.status_code in (401, 403):
        raise FcOnlineApiError(
            "FC Online API authentication failed.",
            status_code=response.status_code,
        )
    if response.status_code == 404:
        raise FcOnlineApiError(
            "FC Online account or match was not found.",
            status_code=404,
        )
    if response.status_code == 429:
        raise FcOnlineApiError(
            "FC Online API rate limit exceeded.",
            status_code=429,
            retry_after=_retry_after_seconds(response),
        )
    if response.status_code >= 400:
        raise FcOnlineApiError(
            "FC Online API request failed.",
            status_code=response.status_code,
        )
    try:
        return response.json()
    except ValueError as exc:
        raise FcOnlineApiError(
            "FC Online API returned an invalid response.",
            status_code=502,
        ) from exc


def fetch_ouid(nickname: str) -> str:
    data = _request_json("/id", params={"nickname": nickname})
    if not isinstance(data, dict) or not data.get("ouid"):
        raise FcOnlineApiError(
            "FC Online account was not found.",
            status_code=404,
        )
    return str(data["ouid"])


def fetch_basic_profile(ouid: str) -> dict[str, Any]:
    data = _request_json("/user/basic", params={"ouid": ouid})
    if not isinstance(data, dict):
        raise FcOnlineApiError(
            "FC Online API returned an invalid basic profile.",
            status_code=502,
        )
    return data


def fetch_max_divisions(ouid: str) -> list[dict[str, Any]]:
    data = _request_json("/user/maxdivision", params={"ouid": ouid})
    if not isinstance(data, list):
        raise FcOnlineApiError(
            "FC Online API returned invalid division data.",
            status_code=502,
        )
    return [item for item in data if isinstance(item, dict)]


def fetch_recent_match_ids(
    ouid: str,
    *,
    match_type: int,
    offset: int = 0,
    limit: int = 5,
) -> list[str]:
    data = _request_json(
        "/user/match",
        params={
            "ouid": ouid,
            "matchtype": match_type,
            "offset": offset,
            "limit": limit,
        },
    )
    if not isinstance(data, list):
        raise FcOnlineApiError(
            "FC Online API returned an invalid match list.",
            status_code=502,
        )
    return [str(match_id) for match_id in data]


def fetch_match_detail(match_id: str) -> dict[str, Any]:
    data = _request_json("/match-detail", params={"matchid": match_id})
    if not isinstance(data, dict):
        raise FcOnlineApiError(
            "FC Online API returned invalid match details.",
            status_code=502,
        )
    return data


def parse_division_metadata(payload: object) -> list[tuple[int, str]]:
    """Parse Nexon metadata while preserving its ranking order."""

    if isinstance(payload, dict):
        for key in ("divisions", "division", "data"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                payload = candidate
                break
    if not isinstance(payload, list):
        return []

    parsed: list[tuple[int, str]] = []
    seen: set[int] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("divisionId", item.get("division_id", item.get("id")))
        raw_name = item.get(
            "divisionName",
            item.get("division_name", item.get("name")),
        )
        try:
            division_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if division_id in seen or raw_name is None:
            continue
        name = str(raw_name).strip()
        if not name:
            continue
        seen.add(division_id)
        parsed.append((division_id, name))
    return parsed


def fetch_division_metadata(
    fallback_payload: object | None = None,
) -> list[tuple[int, str]]:
    """Fetch ordered division metadata, falling back to injected data."""

    try:
        response = _client.get(
            DIVISION_METADATA_URL,
            timeout=_request_timeout(),
        )
        response.raise_for_status()
        parsed = parse_division_metadata(response.json())
        if parsed:
            return parsed
    except (httpx.HTTPError, ValueError):
        logger.warning("FC Online division metadata request failed")
    return parse_division_metadata(fallback_payload)


def _division_lookup(
    metadata: list[tuple[int, str]],
) -> dict[int, tuple[str, int]]:
    # The ordered index is stable and absolute differences preserve proximity.
    return {
        division_id: (name, rank)
        for rank, (division_id, name) in enumerate(metadata, start=1)
    }


def _division_value(
    entries: list[dict[str, Any]],
    match_type: int,
    lookup: dict[int, tuple[str, int]],
) -> DivisionValue:
    for entry in entries:
        try:
            entry_match_type = int(entry.get("matchType"))
        except (TypeError, ValueError):
            continue
        if entry_match_type != match_type:
            continue
        try:
            division_id = int(entry.get("division"))
        except (TypeError, ValueError):
            return DivisionValue(None, None, None)
        metadata = lookup.get(division_id)
        if metadata is None:
            return DivisionValue(division_id, str(division_id), None)
        return DivisionValue(division_id, metadata[0], metadata[1])
    return DivisionValue(None, None, None)


def build_sync_payload(
    *,
    ouid: str,
    basic: dict[str, Any],
    max_divisions: list[dict[str, Any]],
    division_metadata: list[tuple[int, str]],
) -> FcOnlineSyncPayload:
    """Build a normalized profile payload from already-fetched API data."""

    nickname = str(basic.get("nickname") or "").strip()
    if not nickname:
        raise FcOnlineApiError(
            "FC Online API returned an invalid nickname.",
            status_code=502,
        )
    raw_level = basic.get("level")
    try:
        level = int(raw_level) if raw_level is not None else None
    except (TypeError, ValueError):
        level = None
    lookup = _division_lookup(division_metadata)
    return FcOnlineSyncPayload(
        nickname=nickname,
        ouid=ouid,
        level=level,
        division_1v1=_division_value(max_divisions, MATCH_TYPE_1V1, lookup),
        division_2v2=_division_value(max_divisions, MATCH_TYPE_2V2, lookup),
    )


def fetch_sync_payload_for_ouid(
    ouid: str,
    *,
    division_metadata: list[tuple[int, str]] | None = None,
) -> FcOnlineSyncPayload:
    """Fetch all profile fields after an OUID has already been resolved."""

    basic = fetch_basic_profile(ouid)
    max_divisions = fetch_max_divisions(ouid)
    metadata = (
        division_metadata
        if division_metadata is not None
        else fetch_division_metadata()
    )
    return build_sync_payload(
        ouid=ouid,
        basic=basic,
        max_divisions=max_divisions,
        division_metadata=metadata,
    )


def fetch_sync_payload(
    nickname: str,
    *,
    division_metadata: list[tuple[int, str]] | None = None,
) -> FcOnlineSyncPayload:
    """Resolve a nickname and fetch all fields needed for profile sync."""

    return fetch_sync_payload_for_ouid(
        fetch_ouid(nickname),
        division_metadata=division_metadata,
    )


def parse_api_datetime(value: object) -> datetime | None:
    """Parse Nexon's ISO-like date values into aware UTC datetimes."""

    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def result_for_ouid(match_detail: dict[str, Any], ouid: str) -> str | None:
    """Return WIN/DRAW/LOSS for one participant in a match detail payload."""

    result_map = {
        "승": "WIN",
        "win": "WIN",
        "무": "DRAW",
        "draw": "DRAW",
        "패": "LOSS",
        "loss": "LOSS",
        "lose": "LOSS",
    }
    match_info = match_detail.get("matchInfo")
    if not isinstance(match_info, list):
        return None
    for participant in match_info:
        if not isinstance(participant, dict) or str(participant.get("ouid")) != ouid:
            continue
        details = participant.get("matchDetail")
        if not isinstance(details, dict):
            return None
        raw_result = str(details.get("matchResult") or "").strip().lower()
        return result_map.get(raw_result)
    return None
