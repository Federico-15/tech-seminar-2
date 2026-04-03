"""
Kafka Consumer — 8B Pod 진입점 (v8)

KEDA ScaledJob이 이 모듈을 실행합니다.
Kafka 큐에서 CRITICAL 이벤트를 꺼내 Qwen3:30B(8B)로 정밀 분석 후 Aurora에 저장합니다.

실행 방법 (K8s Job 컨테이너 커맨드):
    python -m agents.kafka_consumer
"""
import asyncio
import json
import logging
import sys

from aiokafka import AIOKafkaConsumer

from config.settings import settings
from agents.log_monitor import AnomalyResult
from agents.deep_analysis import run_deep_analysis
from agents.k8s_scaler import switch_to_4b
from storage.aurora_store import init_db, save_analysis_report, save_incident, save_log_analysis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _build_anomaly(msg: dict) -> AnomalyResult:
    return AnomalyResult(
        has_anomaly=True,
        severity=msg.get("severity", "CRITICAL"),
        summary=msg.get("summary", ""),
        details=msg.get("details", ""),
        llm_used=msg.get("llm_used", ""),
        source=msg.get("source", ""),
        raw_content=msg.get("raw_content", ""),
        sensitive=msg.get("sensitive", False),
    )


async def consume_and_analyze() -> None:
    """
    Kafka 큐에서 CRITICAL 이벤트를 소비하고 정밀 분석을 수행합니다.
    큐가 비면 자연스럽게 종료합니다 (KEDA Job 특성).
    """
    logger.info(
        f"[KafkaConsumer] 시작: "
        f"topic={settings.kafka_topic_critical}, "
        f"group={settings.kafka_consumer_group}"
    )

    init_db()

    consumer = AIOKafkaConsumer(
        settings.kafka_topic_critical,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_consumer_group,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        auto_offset_reset="earliest",
        # 메시지 없으면 1초 후 종료 (Job이 큐 소진 후 exit해야 KEDA가 정상 처리)
        consumer_timeout_ms=1000,
    )

    await consumer.start()
    processed = 0
    try:
        async for msg in consumer:
            data = msg.value
            logger.info(
                f"[KafkaConsumer] 메시지 수신: "
                f"severity={data.get('severity')}, summary={data.get('summary', '')[:60]}"
            )

            anomaly = _build_anomaly(data)
            raw_logs = data.get("raw_logs", [])

            # 정밀 분석 (Qwen3:30B 또는 Claude Sonnet)
            report = await run_deep_analysis(anomaly, raw_logs)

            # Aurora 저장
            trigger_id = save_log_analysis(anomaly)
            save_analysis_report(report, trigger_id=trigger_id)
            if anomaly.severity == "CRITICAL":
                save_incident(cause=anomaly.summary)

            processed += 1
            logger.info(f"[KafkaConsumer] 정밀 분석 완료: model={report.model_used}")

    except Exception as e:
        logger.error(f"[KafkaConsumer] 오류: {e}")
    finally:
        await consumer.stop()

    logger.info(f"[KafkaConsumer] 종료 — 처리 {processed}건")

    # 큐 소진 후 8B → 4B Pod 복귀
    if processed > 0:
        try:
            switch_to_4b()
        except Exception as e:
            logger.error(f"[K8sScaler] 4B 복귀 실패: {e}")

    # KEDA Job은 프로세스 종료 코드로 성공/실패를 판단
    sys.exit(0 if processed >= 0 else 1)


if __name__ == "__main__":
    asyncio.run(consume_and_analyze())
