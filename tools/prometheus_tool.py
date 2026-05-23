"""
Prometheus 메트릭 수집 도구 (v8)

Node Exporter 메트릭을 Prometheus HTTP API로 조회합니다.
"""
import logging

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

# PromQL 쿼리 모음
QUERIES = {
    "cpu_usage_percent": (
        "100 - (avg(rate(node_cpu_seconds_total{mode='idle'}[5m])) * 100)"
    ),
    "memory_usage_percent": (
        "(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100"
    ),
    "disk_usage_percent": (
        "100 - (node_filesystem_avail_bytes{mountpoint='/'} "
        "/ node_filesystem_size_bytes{mountpoint='/'} * 100)"
    ),
    "net_receive_kbps": (
        "rate(node_network_receive_bytes_total{device!='lo'}[1m]) / 1024"
    ),
    "net_transmit_kbps": (
        "rate(node_network_transmit_bytes_total{device!='lo'}[1m]) / 1024"
    ),
}


async def fetch_metrics() -> dict:
    """
    Prometheus에서 주요 인프라 메트릭을 조회합니다.

    Returns:
        {
            "cpu_usage_percent": float,
            "memory_usage_percent": float,
            "disk_usage_percent": float,
            "net_receive_kbps": float,
            "net_transmit_kbps": float,
        }
    """
    result = {}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            for metric_name, query in QUERIES.items():
                try:
                    resp = await client.get(
                        f"{settings.prometheus_url}/api/v1/query",
                        params={"query": query},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    value = _extract_value(data)
                    result[metric_name] = value
                except Exception as e:
                    logger.warning(f"[Prometheus] {metric_name} 조회 실패: {e}")
                    result[metric_name] = 0.0

        logger.debug(f"[Prometheus] 메트릭 수집 완료: {result}")
        return result

    except httpx.ConnectError:
        logger.warning(f"[Prometheus] 연결 실패: {settings.prometheus_url}")
        return {}
    except Exception as e:
        logger.error(f"[Prometheus] 수집 오류: {e}")
        return {}


def _extract_value(response_data: dict) -> float:
    """Prometheus 응답에서 첫 번째 숫자 값을 추출합니다."""
    try:
        results = response_data["data"]["result"]
        if not results:
            return 0.0
        # 여러 레이블 결과가 있으면 평균
        values = [float(r["value"][1]) for r in results]
        return sum(values) / len(values)
    except (KeyError, IndexError, ValueError):
        return 0.0
