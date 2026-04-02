from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # -----------------------------------------------------------------------
    # LLM 전략 (환경변수 하나로 전환)
    # CLAUDE_API  → 개발/테스트 (기본값)  — 하이브리드 라우팅 적용
    # QWEN_LOCAL  → 데모 당일             — 모든 트래픽을 vLLM으로
    # -----------------------------------------------------------------------
    llm_provider: Literal["CLAUDE_API", "QWEN_LOCAL"] = "CLAUDE_API"

    # Claude API (개발/테스트용)
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"

    # vLLM — Qwen3:4B (상시 실행, 로그·메트릭 감시용)
    vllm_base_url: str = "http://localhost:8001"
    vllm_4b_model: str = "Qwen/Qwen3-4B"

    # vLLM — Qwen3:30B (이벤트 기반 정밀 분석용, KEDA Pod)
    vllm_deep_url: str = "http://localhost:8002"
    vllm_30b_model: str = "Qwen/Qwen3-30B-A3B-AWQ"

    llm_timeout_seconds: int = 120

    # Loki
    loki_url: str = "http://localhost:3100"
    loki_log_query: str = '{job="app_logs"}'

    # Prometheus
    prometheus_url: str = "http://localhost:9090"

    # 모니터링 설정
    poll_interval_seconds: int = 30
    log_lookback_minutes: int = 5

    # Slack 알림 (선택)
    slack_webhook_url: str = ""

    # Aurora PostgreSQL
    aurora_host: str = ""
    aurora_port: int = 5432
    aurora_db: str = "ai_agent"
    aurora_user: str = ""
    aurora_password: str = ""

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
