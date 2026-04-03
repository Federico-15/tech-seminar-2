"""
Kafka Producer (v8)

CRITICAL 이상 감지 시:
  1. Kafka 큐에 이벤트 적재 (로그 유실 방지)
  2. K8s API로 4B Pod 종료 → 8B Pod 생성 트리거

8B Pod 로딩(~2분) 동안 Kafka 큐가 로그를 보관하고,
8B Pod 준비 완료 후 kafka_consumer.py가 큐에서 꺼내 분석합니다.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

from aiokafka import AIOKafkaProducer

from config.settings import settings
from .log_monitor import AnomalyResult
from .k8s_scaler import switch_to_8b

logger = logging.getLogger(__name__)


async def publish_critical_event(anomaly: AnomalyResult, raw_logs: list[str]) -> bool:
    """
    CRITICAL 이상 감지 결과를 Kafka 큐에 적재하고 8B Pod로 전환합니다.

    Returns:
        성공 여부 (Kafka 발행 기준)
    """
    if not settings.kafka_bootstrap_servers:
        logger.warning("[Kafka] KAFKA_BOOTSTRAP_SERVERS 미설정 — Kafka 발행 스킵")
        return False

    message = {
        "published_at": datetime.now(timezone.utc).isoformat(),
        "severity": anomaly.severity,
        "summary": anomaly.summary,
        "details": anomaly.details,
        "source": anomaly.source,
        "llm_used": anomaly.llm_used,
        "sensitive": anomaly.sensitive,
        "raw_content": anomaly.raw_content,
        "raw_logs": raw_logs[-20:],
    }

    try:
        producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        await producer.start()
        try:
            await producer.send_and_wait(settings.kafka_topic_critical, value=message)
            logger.info(
                f"[Kafka] CRITICAL 이벤트 발행 완료: "
                f"topic={settings.kafka_topic_critical}, severity={anomaly.severity}"
            )
        finally:
            await producer.stop()

    except Exception as e:
        logger.error(f"[Kafka] 발행 실패: {e}")
        return False

    # Kafka 발행 성공 후 4B → 8B Pod 교체
    # 블로킹 K8s API 호출을 이벤트 루프 밖으로 분리
    try:
        await asyncio.get_event_loop().run_in_executor(None, switch_to_8b)
    except Exception as e:
        logger.error(f"[K8sScaler] Pod 교체 실패 (Kafka 발행은 완료됨): {e}")

    return True
