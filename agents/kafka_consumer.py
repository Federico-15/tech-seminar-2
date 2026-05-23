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

import httpx
from aiokafka import AIOKafkaConsumer, TopicPartition

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


async def _wait_for_8b_ready(timeout: int = 300, interval: int = 10) -> bool:
    """
    vLLM 8B 서버가 준비될 때까지 대기합니다.
    timeout: 최대 대기 시간 (초), interval: 헬스체크 간격 (초)
    """
    url = f"{settings.vllm_deep_url}/health"
    logger.info(f"[KafkaConsumer] 8B 모델 준비 대기 중... (최대 {timeout}초)")
    async with httpx.AsyncClient(timeout=5) as client:
        for elapsed in range(0, timeout, interval):
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    logger.info(f"[KafkaConsumer] 8B 모델 준비 완료 ({elapsed}초 소요)")
                    return True
            except Exception:
                pass
            logger.info(f"[KafkaConsumer] 8B 아직 로딩 중... ({elapsed}초 경과)")
            await asyncio.sleep(interval)
    logger.error(f"[KafkaConsumer] 8B 모델 준비 타임아웃 ({timeout}초)")
    return False


def _do_switch_to_4b() -> None:
    """8B → 4B 복귀. 예외를 삼키지 않고 로깅만 한다."""
    try:
        switch_to_4b()
    except Exception as e:
        logger.error(f"[K8sScaler] 4B 복귀 실패: {e}")


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

    # 8B 모델 로딩 완료까지 대기 (최대 5분)
    ready = await _wait_for_8b_ready(timeout=300, interval=10)
    if not ready:
        logger.error("[KafkaConsumer] 8B 모델 미준비 — 4B 복귀 후 종료")
        _do_switch_to_4b()
        sys.exit(1)

    consumer = AIOKafkaConsumer(
        settings.kafka_topic_critical,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_consumer_group,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        auto_commit_interval_ms=1000,
        # LLM 분석 중 poll 없어도 rebalance 안 되게 10분으로 늘림
        max_poll_interval_ms=600000,
        # 메시지 없으면 3초 후 종료 (Job이 큐 소진 후 exit해야 KEDA가 정상 처리)
        consumer_timeout_ms=3000,
    )

    agent_host = settings.agent_server_url
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
            # trigger_id는 server.py가 이미 save_log_analysis()로 저장한 id — 중복 저장 방지
            trigger_id = data.get("trigger_id")
            if trigger_id is None:
                # 하위 호환: trigger_id 없는 구버전 메시지
                trigger_id = save_log_analysis(anomaly)
            save_analysis_report(report, trigger_id=trigger_id)
            if anomaly.severity == "CRITICAL":
                save_incident(cause=anomaly.summary)

            processed += 1
            logger.info(f"[KafkaConsumer] 정밀 분석 완료: model={report.model_used}")

            # 모델 호출 수 보고 → server.py Prometheus 메트릭에 반영
            if report.model_used not in ("error",):
                try:
                    async with httpx.AsyncClient(timeout=3) as client:
                        await client.post(f"{agent_host}/metrics/model-usage/{report.model_used}")
                except Exception:
                    pass

            # 메시지 처리 후 LAG 확인 — 큐가 비었으면 즉시 종료
            tp = TopicPartition(msg.topic, msg.partition)
            end_offsets = await consumer.end_offsets([tp])
            current = consumer.position(tp)
            if current >= end_offsets[tp]:
                logger.info("[KafkaConsumer] 큐 소진 확인 — 종료")
                break

    except Exception as e:
        logger.error(f"[KafkaConsumer] 오류: {e}")
    finally:
        await consumer.stop()

    logger.info(f"[KafkaConsumer] 종료 — 처리 {processed}건")

    # 큐 소진 후 pending 카운터 리셋 (처리 건수 무관하게 항상 실행)
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(f"{agent_host}/metrics/pending-jobs/reset")
        logger.info("[KafkaConsumer] pending_kafka_jobs 카운터 리셋 완료")
    except Exception as e:
        logger.warning(f"[KafkaConsumer] pending 카운터 리셋 실패 (무시): {e}")

    # 8B → 4B 복귀 (처리 건수 무관하게 항상 실행 — 8B Pod를 반드시 해제해야 함)
    _do_switch_to_4b()

    # KEDA Job은 프로세스 종료 코드로 성공/실패를 판단
    sys.exit(0 if processed > 0 else 1)


if __name__ == "__main__":
    asyncio.run(consume_and_analyze())
