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
from fastapi.responses import JSONResponse, PlainTextResponse

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
    "model_usage": {"qwen3:4b": 0, "qwen3:8b": 0, "claude-sonnet": 0},  # 모델별 호출 횟수
    "severity_counts": {},     # severity별 감지 횟수 {"HIGH": 2, "CRITICAL": 0}
    "model_up": {"qwen3_4b": 0, "qwen3_8b": 0},  # 모델 가동 상태 캐시
}


# ---------------------------------------------------------------------------
# 모니터링 루프
# ---------------------------------------------------------------------------

async def run_monitoring_cycle() -> None:
    """로그 + 메트릭 분석 1사이클."""
    logger.info("[Monitor] 사이클 시작")

    # 마지막 폴링 시점 이후 로그만 가져옴 (중복 분석 방지)
    last_poll = _state["last_poll_at"]
    since_dt = datetime.fromisoformat(last_poll) if last_poll else None

    # 로그/메트릭 병렬 수집
    logs, metrics = await asyncio.gather(
        fetch_recent_logs(minutes=settings.log_lookback_minutes, since=since_dt),
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

    # 8B 분석 진행 중(pending > 0)이면 새 CRITICAL을 처리하지 않는다.
    # → DB 저장·Kafka 발행·Pod 전환 모두 스킵 (큐 누적·무한 사이클 방지)
    critical_busy = _state["pending_kafka_jobs"] > 0

    anomalies = []

    if not isinstance(log_result, Exception):
        if log_result.llm_used and log_result.llm_used not in ("none", "error"):
            model = log_result.llm_used
            _state["model_usage"][model] = _state["model_usage"].get(model, 0) + 1
        if log_result.has_anomaly:
            if log_result.severity == "CRITICAL" and critical_busy:
                logger.debug(
                    f"[Monitor] CRITICAL 감지됐으나 8B 분석 진행 중 — 스킵 "
                    f"(pending={_state['pending_kafka_jobs']})"
                )
            else:
                record_id = save_log_analysis(log_result)
                anomalies.append((log_result, record_id, logs))
                logger.info(f"[Monitor] 로그 이상: severity={log_result.severity}, id={record_id}")
                sev = log_result.severity
                _state["severity_counts"][sev] = _state["severity_counts"].get(sev, 0) + 1

    if not isinstance(metric_result, Exception):
        if metric_result.llm_used and metric_result.llm_used not in ("none", "error"):
            model = metric_result.llm_used
            _state["model_usage"][model] = _state["model_usage"].get(model, 0) + 1
        if metric_result.has_anomaly:
            if metric_result.severity == "CRITICAL" and critical_busy:
                logger.debug(
                    f"[Monitor] CRITICAL 감지됐으나 8B 분석 진행 중 — 스킵 (메트릭)"
                )
            else:
                record_id = save_log_analysis(metric_result)
                anomalies.append((metric_result, record_id, []))
                logger.info(f"[Monitor] 메트릭 이상: severity={metric_result.severity}, id={record_id}")
                sev = metric_result.severity
                _state["severity_counts"][sev] = _state["severity_counts"].get(sev, 0) + 1

    # HIGH/CRITICAL → 정밀 분석
    # CRITICAL: Kafka 큐에 적재 → KEDA가 8B Pod 생성 → kafka_consumer.py가 처리
    # HIGH:     직접 deep_analysis 호출 (4B Pod 유지한 채 처리)
    for result, trigger_id, raw_logs in anomalies:
        if result.severity == "CRITICAL":
            try:
                published = await publish_critical_event(
                    result, raw_logs, trigger_id=trigger_id
                )
                if published:
                    _state["pending_kafka_jobs"] += 1
                    logger.info(
                        f"[Monitor] CRITICAL → Kafka 발행·8B 전환 완료 "
                        f"(pending={_state['pending_kafka_jobs']})"
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


async def _check_model_health() -> None:
    """모델 가동 상태를 30초마다 조용히 체크 (로그 없음)."""
    while True:
        for model_name, url in [("qwen3_4b", settings.vllm_base_url), ("qwen3_8b", settings.vllm_deep_url)]:
            try:
                async with httpx.AsyncClient(timeout=2) as client:
                    r = await client.get(f"{url}/health")
                    _state["model_up"][model_name] = 1 if r.status_code == 200 else 0
            except Exception:
                _state["model_up"][model_name] = 0
        await asyncio.sleep(30)


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
    asyncio.create_task(_check_model_health())
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


@app.post("/metrics/model-usage/{model_name}")
async def increment_model_usage(model_name: str):
    """외부 프로세스(kafka_consumer)가 모델 호출 수를 보고하는 엔드포인트."""
    _state["model_usage"][model_name] = _state["model_usage"].get(model_name, 0) + 1
    return {"model": model_name, "total": _state["model_usage"][model_name]}


@app.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics():
    """Prometheus 스크랩용 메트릭 엔드포인트."""
    lines = []

    # 모델별 호출 횟수
    lines.append("# HELP ai_agent_model_usage_total LLM 모델별 호출 횟수")
    lines.append("# TYPE ai_agent_model_usage_total counter")
    for model, count in _state["model_usage"].items():
        lines.append(f'ai_agent_model_usage_total{{model="{model}"}} {count}')

    # severity별 감지 횟수
    lines.append("# HELP ai_agent_severity_total severity별 이상 감지 횟수")
    lines.append("# TYPE ai_agent_severity_total counter")
    for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        count = _state["severity_counts"].get(sev, 0)
        lines.append(f'ai_agent_severity_total{{severity="{sev}"}} {count}')

    # pending kafka jobs
    lines.append("# HELP ai_agent_pending_kafka_jobs KEDA 대기 중인 CRITICAL 이벤트 수")
    lines.append("# TYPE ai_agent_pending_kafka_jobs gauge")
    lines.append(f'ai_agent_pending_kafka_jobs {_state["pending_kafka_jobs"]}')

    # 총 이상 감지 수
    lines.append("# HELP ai_agent_total_anomalies 누적 이상 감지 수")
    lines.append("# TYPE ai_agent_total_anomalies counter")
    lines.append(f'ai_agent_total_anomalies {_state["total_anomalies"]}')

    # 모델 Pod 가동 상태 (1=up, 0=down)
    lines.append("# HELP ai_agent_model_up 모델 Pod 가동 상태 (1=실행중, 0=중지)")
    lines.append("# TYPE ai_agent_model_up gauge")
    for model_name, up in _state["model_up"].items():
        lines.append(f'ai_agent_model_up{{model="{model_name}"}} {up}')

    return "\n".join(lines) + "\n"


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
