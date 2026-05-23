"""
하이브리드 LLM 라우터 (v8)

민감 로그 → Qwen3 내부 처리 (외부 유출 차단)
일반 로그 → Claude API 외부 처리 (빠른 응답)

QWEN_LOCAL 모드에서는 모든 트래픽이 vLLM으로 라우팅됩니다.
"""
import json
import logging
from typing import Any

import httpx
from anthropic import Anthropic

from config.settings import settings

logger = logging.getLogger(__name__)

def is_sensitive(content: str) -> bool:
    """로그에 [PII] 태그가 있으면 민감 데이터로 분류."""
    return "[PII]" in content


def route_llm(log_content: str) -> str:
    """민감도에 따라 'qwen' 또는 'claude' 반환."""
    return "qwen" if is_sensitive(log_content) else "claude"


def call_llm(prompt: str, system: str = "", log_content: str = "") -> tuple[str, str]:
    """
    LLM을 호출하고 (응답 텍스트, 모델명) 튜플을 반환합니다.

    QWEN_LOCAL 모드: 모든 트래픽 → Qwen3:4B (vLLM)
    CLAUDE_API 모드: 민감 로그 → Qwen3:4B, 일반 로그 → Claude
    """
    if settings.llm_provider == "QWEN_LOCAL":
        return _call_vllm(prompt, system, settings.vllm_base_url, settings.vllm_4b_model), "qwen3:4b"

    # 민감 로그 → Qwen3:4B (공통)
    if is_sensitive(log_content):
        try:
            result = _call_vllm(prompt, system, settings.vllm_base_url, settings.vllm_4b_model)
            return result, "qwen3:4b"
        except Exception as e:
            logger.warning(f"[LLMRouter] 민감 로그 — Qwen3 미응답, 외부 폴백 (보안 주의): {e}")

    return _call_claude(prompt, system), "claude-sonnet"


def call_llm_local_4b(prompt: str, system: str = "") -> tuple[str, str]:
    """
    항상 qwen3:4b(vLLM)로 호출. 메트릭 등 내부 데이터 전용.
    4B→8B 전환 중 응답 불가 시 폴백 없이 예외를 올린다.
    (CRITICAL은 Kafka가 버퍼링하므로 Claude 폴백 불필요)
    """
    result = _call_vllm(prompt, system, settings.vllm_base_url, settings.vllm_4b_model)
    return result, "qwen3:4b"


def call_llm_deep(prompt: str, system: str = "") -> tuple[str, str]:
    """
    정밀 분석 전용 LLM 호출 — 항상 qwen3:8b(vLLM deep endpoint).
    Claude는 외부 로그 분석 전용이므로 심층 분석에 사용하지 않는다.
    """
    return _call_vllm(prompt, system, settings.vllm_deep_url, settings.vllm_30b_model), "qwen3:8b"


def _call_claude(prompt: str, system: str) -> str:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY 미설정")
    client = Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=settings.claude_model,
        max_tokens=4096,
        system=system or "You are a helpful infrastructure monitoring assistant.",
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _call_vllm(prompt: str, system: str, base_url: str, model: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system or "You are a helpful assistant."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 4096,
    }
    with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
        resp = client.post(f"{base_url}/v1/chat/completions", json=payload)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        # Qwen3 thinking 블록 제거 (<think>...</think>)
        if "<think>" in content and "</think>" in content:
            content = content[content.index("</think>") + len("</think>"):].strip()
        return content


def parse_json_response(text: str) -> Any:
    """LLM 응답에서 JSON을 파싱합니다. 마크다운 코드블록 처리 포함."""
    if "```" in text:
        for part in text.split("```"):
            stripped = part.strip().lstrip("json").strip()
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                continue
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for start_char, end_char in [("{", "}"), ("[", "]")]:
            start = text.find(start_char)
            end = text.rfind(end_char) + 1
            if start != -1 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    continue
        raise
