"""
로그 분석 에이전트 (v8)

Loki에서 수집한 로그를 하이브리드 LLM으로 분석합니다.
민감 로그(password, token 등) → Qwen3 내부 처리
일반 로그 → Claude API (또는 Qwen3 — QWEN_LOCAL 모드)
"""
import logging
from dataclasses import dataclass, field

from .llm_router import call_llm, is_sensitive, parse_json_response

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an infrastructure log analyzer.
Analyze logs for anomalies: errors, authentication failures, timeouts, performance degradation.
Always respond with valid JSON only, no explanation outside JSON."""

ANALYSIS_PROMPT = """Analyze the following infrastructure logs for anomalies:

{logs}

Return JSON:
{{
  "has_anomaly": true or false,
  "severity": "CRITICAL|HIGH|MEDIUM|LOW|NORMAL",
  "summary": "한 줄 요약 (한국어)",
  "details": "상세 설명 (한국어)"
}}

Severity guidelines:
- CRITICAL: 서비스 다운, 데이터 유실 위험, 인증 시스템 오류
- HIGH: 다수 에러 반복, 응답 지연 심각, DB 연결 실패
- MEDIUM: 경고 신호 증가, 에러율 상승
- LOW: 산발적 경고, 경미한 이슈
- NORMAL: 정상 범위"""


@dataclass
class AnomalyResult:
    has_anomaly: bool
    severity: str        # CRITICAL, HIGH, MEDIUM, LOW, NORMAL
    summary: str
    details: str
    llm_used: str
    source: str = ""     # loki, prometheus
    raw_content: str = ""
    sensitive: bool = False


async def analyze_logs(logs: list[str]) -> AnomalyResult:
    """
    로그 목록을 분석하여 이상 징후를 반환합니다.
    민감 여부를 판별하고 적절한 LLM으로 라우팅합니다.
    """
    if not logs:
        return AnomalyResult(
            has_anomaly=False, severity="NORMAL",
            summary="수집된 로그 없음", details="", llm_used="none",
        )

    log_text = "\n".join(logs[-50:])  # 최근 50줄
    sensitive = is_sensitive(log_text)

    if sensitive:
        logger.info(f"[LogMonitor] 민감 로그 감지 → Qwen3 내부 처리")
    else:
        logger.debug(f"[LogMonitor] 일반 로그 → {_route_label()}")

    prompt = ANALYSIS_PROMPT.format(logs=log_text)

    try:
        response, model_used = call_llm(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            log_content=log_text,
        )
        parsed = parse_json_response(response)
        return AnomalyResult(
            has_anomaly=bool(parsed.get("has_anomaly", False)),
            severity=parsed.get("severity", "NORMAL").upper(),
            summary=parsed.get("summary", ""),
            details=parsed.get("details", ""),
            llm_used=model_used,
            source="loki",
            raw_content=log_text[:1000],
            sensitive=sensitive,
        )
    except Exception as e:
        logger.error(f"[LogMonitor] 분석 실패: {e}")
        return AnomalyResult(
            has_anomaly=False, severity="NORMAL",
            summary=f"분석 오류: {str(e)[:100]}", details="", llm_used="error",
        )


def _route_label() -> str:
    from config.settings import settings
    return "Qwen3:4B" if settings.llm_provider == "QWEN_LOCAL" else "Claude API"
