"""
메트릭 분석 에이전트 (v8)

Prometheus에서 수집한 CPU/메모리/디스크 메트릭을 분석합니다.
메트릭은 내부 인프라 데이터이므로 항상 Qwen3(내부)로 처리합니다.
(QWEN_LOCAL 미설정 시에는 Claude API 사용)
"""
import logging

from .llm_router import call_llm, parse_json_response
from .log_monitor import AnomalyResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an infrastructure metrics analyzer.
Analyze CPU, memory, disk, and network metrics for anomalies.
Always respond with valid JSON only."""

ANALYSIS_PROMPT = """Analyze the following infrastructure metrics:

CPU 사용률:    {cpu:.1f}%
메모리 사용률: {memory:.1f}%
디스크 사용률: {disk:.1f}%
네트워크 수신: {net_in:.1f} KB/s
네트워크 송신: {net_out:.1f} KB/s

Return JSON:
{{
  "has_anomaly": true or false,
  "severity": "CRITICAL|HIGH|MEDIUM|LOW|NORMAL",
  "summary": "한 줄 요약 (한국어)",
  "details": "상세 설명 (한국어)"
}}

Severity guidelines:
- CRITICAL: CPU/메모리 95% 초과, 서비스 불가 위험
- HIGH: CPU 85% 초과 또는 메모리 90% 초과
- MEDIUM: CPU 70% 초과 또는 메모리 80% 초과
- LOW: 경미한 사용률 상승
- NORMAL: 정상 범위"""


async def analyze_metrics(metrics: dict) -> AnomalyResult:
    """
    Prometheus 메트릭을 분석하여 이상 징후를 반환합니다.
    메트릭은 내부 데이터이므로 민감도 라우팅 없이 기본 LLM 사용.
    """
    if not metrics:
        return AnomalyResult(
            has_anomaly=False, severity="NORMAL",
            summary="수집된 메트릭 없음", details="", llm_used="none", source="prometheus",
        )

    prompt = ANALYSIS_PROMPT.format(
        cpu=metrics.get("cpu_usage_percent", 0.0),
        memory=metrics.get("memory_usage_percent", 0.0),
        disk=metrics.get("disk_usage_percent", 0.0),
        net_in=metrics.get("net_receive_kbps", 0.0),
        net_out=metrics.get("net_transmit_kbps", 0.0),
    )

    try:
        # 메트릭은 내부 데이터 — log_content="" 로 전달하여 민감도 우회
        response, model_used = call_llm(prompt=prompt, system=SYSTEM_PROMPT, log_content="")
        parsed = parse_json_response(response)
        return AnomalyResult(
            has_anomaly=bool(parsed.get("has_anomaly", False)),
            severity=parsed.get("severity", "NORMAL").upper(),
            summary=parsed.get("summary", ""),
            details=parsed.get("details", ""),
            llm_used=model_used,
            source="prometheus",
            raw_content=str(metrics)[:500],
        )
    except Exception as e:
        logger.error(f"[MetricMonitor] 분석 실패: {e}")
        return AnomalyResult(
            has_anomaly=False, severity="NORMAL",
            summary=f"분석 오류: {str(e)[:100]}", details="", llm_used="error",
            source="prometheus",
        )
