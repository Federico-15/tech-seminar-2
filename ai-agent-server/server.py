"""
AI Agent Server v8 — LLM 기반 실시간 인프라 모니터링

Loki 로그 + Prometheus 메트릭 → 하이브리드 LLM 라우팅 → 이상 감지 → Aurora 저장
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from config.settings import settings
from agents import analyze_logs, analyze_metrics, run_deep_analysis
from agents.kafka_producer import publish_critical_event
from tools.loki_tool import fetch_recent_logs
from tools.prometheus_tool import fetch_metrics
from storage.aurora_store import (
    init_db,
    save_log_analysis,
    save_analysis_report,
    save_incident,
    save_alert,
    get_recent_log_analysis,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_state: dict[str, Any] = {
    "running": False,
    "last_poll_at": None,
    "total_anomalies": 0,
    "last_anomaly_at": None,
    "pending_kafka_jobs": 0,   # KEDA /metrics/pending-jobs 용
}


# ---------------------------------------------------------------------------
# 모니터링 루프
# ---------------------------------------------------------------------------

async def run_monitoring_cycle() -> None:
    """로그 + 메트릭 분석 1사이클."""
    logger.info("[Monitor] 사이클 시작")

    # 로그/메트릭 병렬 수집
    logs, metrics = await asyncio.gather(
        fetch_recent_logs(minutes=settings.log_lookback_minutes),
        fetch_metrics(),
        return_exceptions=True,
    )
    if isinstance(logs, Exception):
        logger.warning(f"[Monitor] Loki 수집 실패: {logs}")
        logs = []
    if isinstance(metrics, Exception):
        logger.warning(f"[Monitor] Prometheus 수집 실패: {metrics}")
        metrics = {}

    # 로그/메트릭 분석 병렬 실행
    log_result, metric_result = await asyncio.gather(
        analyze_logs(logs),
        analyze_metrics(metrics),
        return_exceptions=True,
    )

    anomalies = []

    if not isinstance(log_result, Exception) and log_result.has_anomaly:
        record_id = save_log_analysis(log_result)
        anomalies.append((log_result, record_id, logs))
        logger.info(f"[Monitor] 로그 이상: severity={log_result.severity}, id={record_id}")

    if not isinstance(metric_result, Exception) and metric_result.has_anomaly:
        record_id = save_log_analysis(metric_result)
        anomalies.append((metric_result, record_id, []))
        logger.info(f"[Monitor] 메트릭 이상: severity={metric_result.severity}, id={record_id}")

    # HIGH/CRITICAL → 정밀 분석
    # CRITICAL: Kafka 큐에 적재 → KEDA가 8B Pod 생성 → kafka_consumer.py가 처리
    # HIGH:     직접 deep_analysis 호출 (4B Pod 유지한 채 처리)
    for result, trigger_id, raw_logs in anomalies:
        if result.severity == "CRITICAL":
            try:
                published = await publish_critical_event(result, raw_logs)
                if published:
                    _state["pending_kafka_jobs"] += 1
                    logger.info(
                        f"[Monitor] CRITICAL → Kafka 발행 완료 "
                        f"(pending={_state['pending_kafka_jobs']}). "
                        f"KEDA가 8B Pod를 생성합니다."
                    )
                else:
                    # Kafka 미설정 시 fallback: 직접 정밀 분석
                    report = await run_deep_analysis(result, raw_logs)
                    save_analysis_report(report, trigger_id=trigger_id)
                    save_incident(cause=result.summary)
            except Exception as e:
                logger.error(f"[Monitor] CRITICAL 처리 실패: {e}")

        elif result.severity == "HIGH":
            try:
                report = await run_deep_analysis(result, raw_logs)
                save_analysis_report(report, trigger_id=trigger_id)
            except Exception as e:
                logger.error(f"[Monitor] HIGH 정밀 분석 실패: {e}")

        await _notify_slack(result, trigger_id)

    _state["last_poll_at"] = datetime.now(timezone.utc).isoformat()
    if anomalies:
        _state["total_anomalies"] += len(anomalies)
        _state["last_anomaly_at"] = datetime.now(timezone.utc).isoformat()

    logger.info(f"[Monitor] 사이클 완료 — 이상 {len(anomalies)}건")


async def _notify_slack(result, trigger_id: int | None) -> None:
    """Slack Webhook으로 알림 발송 (MEDIUM 이상일 때만)."""
    if not settings.slack_webhook_url:
        return
    if result.severity not in ("CRITICAL", "HIGH", "MEDIUM"):
        return

    emoji = {"CRITICAL": "🚨", "HIGH": "🔴", "MEDIUM": "🟡"}.get(result.severity, "ℹ️")
    message = f"{emoji} *[{result.severity}]* {result.summary}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(settings.slack_webhook_url, json={"text": message})
        save_alert(channel="slack", message=message, trigger_id=trigger_id)
        logger.info(f"[Slack] 알림 발송: {message}")
    except Exception as e:
        logger.error(f"[Slack] 알림 실패: {e}")


async def _monitoring_loop() -> None:
    _state["running"] = True
    logger.info(f"[Monitor] 루프 시작 (폴링 간격: {settings.poll_interval_seconds}s)")
    while True:
        try:
            await run_monitoring_cycle()
        except Exception as e:
            logger.error(f"[Monitor] 사이클 오류: {e}")
        await asyncio.sleep(settings.poll_interval_seconds)


# ---------------------------------------------------------------------------
# FastAPI 앱
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== AI Agent Server v8 시작 ===")
    logger.info(f"LLM Provider : {settings.llm_provider}")
    logger.info(f"Loki URL     : {settings.loki_url}")
    logger.info(f"Prometheus   : {settings.prometheus_url}")
    logger.info(f"Poll 간격    : {settings.poll_interval_seconds}s")
    init_db()
    asyncio.create_task(_monitoring_loop())
    yield
    _state["running"] = False
    logger.info("=== AI Agent Server v8 종료 ===")


app = FastAPI(
    title="AI Agent Server",
    description="LLM 기반 실시간 인프라 모니터링 — K8s GPU 스케줄링 + DR 재해복구 데모",
    version="8.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    """헬스체크."""
    return {"status": "ok", "version": "8.0.0", "llm_provider": settings.llm_provider}


@app.get("/status")
async def get_status():
    """모니터링 현황 조회."""
    return {
        "running": _state["running"],
        "llm_provider": settings.llm_provider,
        "poll_interval_seconds": settings.poll_interval_seconds,
        "last_poll_at": _state["last_poll_at"],
        "total_anomalies": _state["total_anomalies"],
        "last_anomaly_at": _state["last_anomaly_at"],
    }


@app.post("/trigger")
async def manual_trigger():
    """수동 분석 트리거 — 데모/테스트용."""
    asyncio.create_task(run_monitoring_cycle())
    return {"message": "분석 트리거됨"}


@app.get("/metrics/pending-jobs")
async def pending_jobs():
    """
    KEDA metrics-api 트리거용 엔드포인트.
    Kafka로 발행된 미처리 CRITICAL 이벤트 수를 반환합니다.
    KEDA가 이 값을 감지해 8B Pod 생성 여부를 결정합니다.
    """
    return {"pending_count": _state["pending_kafka_jobs"]}


@app.post("/metrics/pending-jobs/reset")
async def reset_pending_jobs():
    """8B Pod 분석 완료 후 호출 — pending 카운터를 초기화합니다."""
    _state["pending_kafka_jobs"] = 0
    return {"message": "pending_count 초기화 완료"}


@app.get("/history")
async def get_history(limit: int = 20):
    """
    최근 이상 감지 이력 조회.
    Grafana Aurora 패널 + DR 시연(DB 장애 → 조회 실패 → Failover → 복구)에 사용됩니다.
    """
    records = get_recent_log_analysis(limit=limit)
    return {"records": records, "count": len(records)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host=settings.host, port=settings.port, reload=False)
