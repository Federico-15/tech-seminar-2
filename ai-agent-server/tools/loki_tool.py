"""
Loki 로그 수집 도구 (v8)

Loki HTTP API로 최근 N분간의 로그를 가져옵니다.
"""
import logging
import time
from datetime import datetime, timezone, timedelta

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)


async def fetch_recent_logs(minutes: int = 5, limit: int = 100) -> list[str]:
    """
    Loki에서 최근 N분간의 로그를 가져와 문자열 리스트로 반환합니다.

    Returns:
        로그 라인 문자열 리스트 (오래된 것 → 최신 순)
    """
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=minutes)

    params = {
        "query": settings.loki_log_query,
        "start": _to_nanoseconds(start),
        "end": _to_nanoseconds(now),
        "limit": limit,
        "direction": "forward",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{settings.loki_url}/loki/api/v1/query_range",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        lines = []
        for stream in data.get("data", {}).get("result", []):
            for _, log_line in stream.get("values", []):
                lines.append(log_line)

        logger.debug(f"[Loki] {len(lines)}개 로그 수집 (최근 {minutes}분)")
        return lines

    except httpx.ConnectError:
        logger.warning(f"[Loki] 연결 실패: {settings.loki_url} — Loki가 실행 중인지 확인하세요")
        return []
    except Exception as e:
        logger.error(f"[Loki] 수집 오류: {e}")
        return []


def _to_nanoseconds(dt: datetime) -> str:
    """datetime을 Loki API용 나노초 타임스탬프 문자열로 변환합니다."""
    return str(int(dt.timestamp() * 1_000_000_000))
