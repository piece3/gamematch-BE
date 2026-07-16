"""Riot Games API 클라이언트 (티어 조회).

API 키는 환경변수 RIOT_API_KEY 만 사용. 소스에 하드코딩하지 말 것.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

SOLO_QUEUE = "RANKED_SOLO_5x5"

# Riot API queue → 우리 LoLTier 값
_TIER_MAP = {
    "IRON": "IRON",
    "BRONZE": "BRONZE",
    "SILVER": "SILVER",
    "GOLD": "GOLD",
    "PLATINUM": "PLATINUM",
    "EMERALD": "EMERALD",
    "DIAMOND": "DIAMOND",
    "MASTER": "MASTER",
    "GRANDMASTER": "GRANDMASTER",
    "CHALLENGER": "CHALLENGER",
}


class RiotApiError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        retry_after: int | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


@dataclass
class RiotRankResult:
    riot_id: str
    puuid: str
    tier: str  # UN_RANKED or mapped tier
    rank_division: str | None = None
    league_points: int | None = None
    queue_type: str | None = None


def parse_riot_id(riot_id: str) -> tuple[str, str]:
    """'게임이름#태그' → (gameName, tagLine)."""
    raw = riot_id.strip()
    if "#" not in raw:
        raise RiotApiError(
            "Riot ID는 '닉네임#태그' 형식이어야 합니다. 예: Hide on bush#KR1",
            status_code=400,
        )
    game_name, tag_line = raw.rsplit("#", 1)
    game_name = game_name.strip()
    tag_line = tag_line.strip()
    if not game_name or not tag_line:
        raise RiotApiError(
            "Riot ID는 '닉네임#태그' 형식이어야 합니다.",
            status_code=400,
        )
    return game_name, tag_line


def _headers() -> dict[str, str]:
    key = (settings.riot_api_key or "").strip()
    if not key:
        raise RiotApiError(
            "RIOT_API_KEY가 설정되지 않았습니다. .env 또는 Render Environment에 추가하세요.",
            status_code=503,
        )
    return {"X-Riot-Token": key}


_client = httpx.Client(
    timeout=15.0,
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
)


def _retry_after_seconds(response: httpx.Response) -> int | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0, int(value))
    except ValueError:
        return None


def _get_json(url: str) -> object:
    resp: httpx.Response | None = None
    for attempt in range(2):
        try:
            resp = _client.get(url, headers=_headers())
        except httpx.HTTPError as exc:
            if attempt == 0:
                time.sleep(0.25)
                continue
            logger.exception("Riot API network error")
            raise RiotApiError(
                f"Riot API 네트워크 오류: {exc}",
                status_code=502,
            ) from exc

        retry_after = _retry_after_seconds(resp)
        retryable = resp.status_code in (429, 502, 503, 504)
        if retryable and attempt == 0:
            delay = retry_after if retry_after is not None else 0.25
            if delay <= 2:
                time.sleep(delay)
                continue
        break

    if resp is None:
        raise RiotApiError("Riot API 응답을 받지 못했습니다.")

    if resp.status_code == 401 or resp.status_code == 403:
        raise RiotApiError(
            "Riot API 키가 유효하지 않거나 만료되었습니다. Developer Portal에서 갱신하세요.",
            status_code=resp.status_code,
        )
    if resp.status_code == 404:
        raise RiotApiError("Riot 계정을 찾을 수 없습니다. Riot ID를 확인하세요.", status_code=404)
    if resp.status_code == 429:
        retry_after = _retry_after_seconds(resp)
        raise RiotApiError(
            "Riot API rate limit. 잠시 후 다시 시도하세요.",
            status_code=429,
            retry_after=retry_after,
        )
    if resp.status_code >= 400:
        raise RiotApiError(
            f"Riot API 오류 ({resp.status_code}): {resp.text[:200]}",
            status_code=resp.status_code,
        )
    return resp.json()


def fetch_account_by_riot_id(riot_id: str) -> dict:
    game_name, tag_line = parse_riot_id(riot_id)
    regional = settings.riot_regional
    url = (
        f"https://{regional}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/"
        f"{quote(game_name, safe='')}/{quote(tag_line, safe='')}"
    )
    data = _get_json(url)
    if not isinstance(data, dict) or "puuid" not in data:
        raise RiotApiError("Riot Account API 응답이 올바르지 않습니다.")
    return data


def fetch_solo_rank_by_puuid(
    puuid: str,
) -> tuple[str, str | None, int | None]:
    """Return solo queue tier, division, and league points."""
    platform = settings.riot_platform
    url = f"https://{platform}.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}"
    data = _get_json(url)
    if not isinstance(data, list):
        raise RiotApiError("Riot League API 응답이 올바르지 않습니다.")

    for entry in data:
        if entry.get("queueType") != SOLO_QUEUE:
            continue
        riot_tier = (entry.get("tier") or "").upper()
        mapped = _TIER_MAP.get(riot_tier)
        if mapped:
            division = (entry.get("rank") or "").upper() or None
            league_points = entry.get("leaguePoints")
            return (
                mapped,
                division,
                int(league_points) if league_points is not None else 0,
            )
    return "UN_RANKED", None, None


def fetch_solo_tier_by_puuid(puuid: str) -> str:
    """Backward-compatible tier-only helper."""
    return fetch_solo_rank_by_puuid(puuid)[0]


def fetch_rank_by_riot_id(riot_id: str) -> RiotRankResult:
    """Riot ID → PUUID → 솔랭 티어."""
    account = fetch_account_by_riot_id(riot_id)
    puuid = account["puuid"]
    # 정규화된 riot_id 보관
    game_name = account.get("gameName") or parse_riot_id(riot_id)[0]
    tag_line = account.get("tagLine") or parse_riot_id(riot_id)[1]
    normalized = f"{game_name}#{tag_line}"

    tier, division, league_points = fetch_solo_rank_by_puuid(puuid)
    return RiotRankResult(
        riot_id=normalized,
        puuid=puuid,
        tier=tier,
        rank_division=division,
        league_points=league_points,
        queue_type=SOLO_QUEUE if tier != "UN_RANKED" else None,
    )


def fetch_recent_match_ids(
    puuid: str,
    *,
    queue_id: int,
    count: int = 5,
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
) -> list[str]:
    regional = settings.riot_regional
    params = [f"queue={queue_id}", f"start=0", f"count={count}"]
    if start_time_ms is not None:
        params.append(f"startTime={start_time_ms}")
    if end_time_ms is not None:
        params.append(f"endTime={end_time_ms}")
    url = (
        f"https://{regional}.api.riotgames.com/lol/match/v5/matches/by-puuid/"
        f"{quote(puuid, safe='')}/ids?{'&'.join(params)}"
    )
    data = _get_json(url)
    if not isinstance(data, list):
        raise RiotApiError("Riot Match list 응답이 올바르지 않습니다.")
    return [str(item) for item in data]


def fetch_match_detail(riot_match_id: str) -> dict:
    regional = settings.riot_regional
    url = (
        f"https://{regional}.api.riotgames.com/lol/match/v5/matches/"
        f"{quote(riot_match_id, safe='')}"
    )
    data = _get_json(url)
    if not isinstance(data, dict):
        raise RiotApiError("Riot Match detail 응답이 올바르지 않습니다.")
    return data
