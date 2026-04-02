"""
정밀 분석 에이전트 (v8)

HIGH/CRITICAL 이상 감지 시 Qwen3:30B(또는 Claude Sonnet)로 심층 분석합니다.
KEDA가 Qwen3:30B Pod를 생성한 뒤 vllm_deep_url로 호출됩니다.
"""
import logging
from dataclasses import dataclass

from .llm_router import call_llm_deep
from .log_monitor import AnomalyResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior infrastructure reliability engineer.
Perform deep root cause analysis on detected anomalies.
Provide actionable recommendations. Respond in Korean."""

DEEP_ANALYSIS_PROMPT = """다음 인프라 이상 징후에 대해 심층 분석을 수행하세요.

## 이상 감지 정보
- 심각도: {severity}
- 요약: {summary}
- 상세: {details}
- 데이터 소스: {source}

## 원시 로그/메트릭 (최근)
{raw_content}

다음 항목을 포함하여 분석하세요:
1. 근본 원인 (Root Cause)
2. 영향 범위
3. 즉각 조치 방법 (3단계 이내)
4. 재발 방지 방안
5. 모니터링 강화 포인트"""


@dataclass
class DeepAnalysisReport:
    trigger_severity: str
    trigger_summary: str
    report: str
    model_used: str
    source: str


async def run_deep_analysis(anomaly: AnomalyResult, raw_logs: list[str]) -> DeepAnalysisReport:
    """
    이상 결과를 받아 Qwen3:30B(또는 Claude Sonnet)로 심층 분석합니다.
    KEDA에 의해 Qwen3:30B Pod가 생성된 후 호출됩니다.
    """
    logger.info(f"[DeepAnalysis] 정밀 분석 시작: severity={anomaly.severity}, source={anomaly.source}")

    raw_content = anomaly.raw_content
    if raw_logs:
        raw_content = "\n".join(raw_logs[-20:])  # 최근 20줄만

    prompt = DEEP_ANALYSIS_PROMPT.format(
        severity=anomaly.severity,
        summary=anomaly.summary,
        details=anomaly.details,
        source=anomaly.source,
        raw_content=raw_content[:2000],
    )

    try:
        report_text, model_used = call_llm_deep(prompt=prompt, system=SYSTEM_PROMPT)
        logger.info(f"[DeepAnalysis] 분석 완료: model={model_used}")
        return DeepAnalysisReport(
            trigger_severity=anomaly.severity,
            trigger_summary=anomaly.summary,
            report=report_text,
            model_used=model_used,
            source=anomaly.source,
        )
    except Exception as e:
        logger.error(f"[DeepAnalysis] 분석 실패: {e}")
        return DeepAnalysisReport(
            trigger_severity=anomaly.severity,
            trigger_summary=anomaly.summary,
            report=f"정밀 분석 실패: {str(e)}",
            model_used="error",
            source=anomaly.source,
        )
