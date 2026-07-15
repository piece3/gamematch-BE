"""Riot Games API 클라이언트 (티어 조회).

API 키는 환경변수 RIOT_API_KEY 만 사용. 소스에 하드코딩하지 말 것.
"""

from __future__ import annotations

import logging
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
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class RiotRankResult:
    riot_id: str
    puuid: str
    tier: str  # UN_RANKED or mapped tier
    queue_type: str | None = None


def parse_riot_id(riot_id: str) -> tuple[str, str]:
    """'게임이름#태그' → (gameName, tagLine)."""
    raw = riot_id.strip()
    if "#" not in raw:
        raise RiotApiError("Riot ID는 '닉네임#태그' 형식이어야 합니다. 예: Hide on bush#KR1")
    game_name, tag_line = raw.rsplit("#", 1)
    game_name = game_name.strip()
    tag_line = tag_line.strip()
    if not game_name or not tag_line:
        raise RiotApiError("Riot ID는 '닉네임#태그' 형식이어야 합니다.")
    return game_name, tag_line


def _headers() -> dict[str, str]:
    key = (settings.riot_api_key or "").strip()
    if not key:
        raise RiotApiError(
            "RIOT_API_KEY가 설정되지 않았습니다. .env 또는 Render Environment에 추가하세요."
        )
    return {"X-Riot-Token": key}


def _get_json(url: str) -> dict | list:
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, headers=_headers())
    except httpx.HTTPError as exc:
        logger.exception("Riot API network error")
        raise RiotApiError(f"Riot API 네트워크 오류: {exc}") from exc

    if resp.status_code == 401 or resp.status_code == 403:
        raise RiotApiError(
            "Riot API 키가 유효하지 않거나 만료되었습니다. Developer Portal에서 갱신하세요.",
            status_code=resp.status_code,
        )
    if resp.status_code == 404:
        raise RiotApiError("Riot 계정을 찾을 수 없습니다. Riot ID를 확인하세요.", status_code=404)
    if resp.status_code == 429:
        raise RiotApiError("Riot API rate limit. 잠시 후 다시 시도하세요.", status_code=429)
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


def fetch_solo_tier_by_puuid(puuid: str) -> str:
    """솔로/듀오 티어명 반환. 랭크 없으면 UN_RANKED."""
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
            return mapped
    return "UN_RANKED"


def fetch_rank_by_riot_id(riot_id: str) -> RiotRankResult:
    """Riot ID → PUUID → 솔랭 티어."""
    account = fetch_account_by_riot_id(riot_id)
    puuid = account["puuid"]
    # 정규화된 riot_id 보관
    game_name = account.get("gameName") or parse_riot_id(riot_id)[0]
    tag_line = account.get("tagLine") or parse_riot_id(riot_id)[1]
    normalized = f"{game_name}#{tag_line}"

    tier = fetch_solo_tier_by_puuid(puuid)
    return RiotRankResult(
        riot_id=normalized,
        puuid=puuid,
        tier=tier,
        queue_type=SOLO_QUEUE if tier != "UN_RANKED" else None,
    )
