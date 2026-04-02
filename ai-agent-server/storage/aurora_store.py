"""
Aurora PostgreSQL 저장소 (v8)

테이블:
  log_analysis    — 로그/메트릭 이상 감지 이력
  analysis_report — Qwen3:30B 심층 분석 리포트
  incident        — 장애 발생/복구 이력
  alert_history   — Slack/이메일 알림 발송 이력
"""
import logging
from datetime import datetime, timezone
from typing import Any

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from config.settings import settings

logger = logging.getLogger(__name__)

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS log_analysis (
    id          SERIAL PRIMARY KEY,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    severity    VARCHAR(10)  NOT NULL,
    summary     TEXT         NOT NULL,
    details     TEXT,
    source      VARCHAR(20)  NOT NULL DEFAULT 'loki',
    llm_used    VARCHAR(30)  NOT NULL,
    sensitive   BOOLEAN      NOT NULL DEFAULT FALSE,
    raw_content TEXT
);

CREATE INDEX IF NOT EXISTS idx_log_analysis_detected_at
    ON log_analysis (detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_log_analysis_severity
    ON log_analysis (severity);

CREATE TABLE IF NOT EXISTS analysis_report (
    id          SERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trigger_id  INTEGER REFERENCES log_analysis(id),
    report      TEXT        NOT NULL,
    model_used  VARCHAR(30) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_analysis_report_created_at
    ON analysis_report (created_at DESC);

CREATE TABLE IF NOT EXISTS incident (
    id               SERIAL PRIMARY KEY,
    started_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cause            TEXT,
    recovered_at     TIMESTAMPTZ,
    duration_seconds INTEGER,
    status           VARCHAR(20) NOT NULL DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS alert_history (
    id         SERIAL PRIMARY KEY,
    sent_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    channel    VARCHAR(20) NOT NULL,
    message    TEXT        NOT NULL,
    trigger_id INTEGER
);
"""


def _get_conn():
    return psycopg2.connect(
        host=settings.aurora_host,
        port=settings.aurora_port,
        dbname=settings.aurora_db,
        user=settings.aurora_user,
        password=settings.aurora_password,
        connect_timeout=10,
        sslmode="require",
    )


def _db_available() -> bool:
    if not settings.aurora_host:
        logger.warning("[Aurora] AURORA_HOST 미설정 — DB 저장 스킵")
        return False
    return True


def init_db() -> None:
    """서버 시작 시 테이블 생성 (없으면)."""
    if not _db_available():
        return
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(CREATE_TABLES_SQL)
        logger.info("[Aurora] 테이블 초기화 완료")
    except Exception as e:
        logger.error(f"[Aurora] 테이블 초기화 실패: {e}")


def save_log_analysis(anomaly, source: str = "") -> int | None:
    """
    이상 감지 결과를 log_analysis 테이블에 저장합니다.

    Args:
        anomaly: AnomalyResult 인스턴스
        source:  'loki' 또는 'prometheus' (anomaly.source 우선)
    Returns:
        저장된 레코드 id (실패 시 None)
    """
    if not _db_available():
        return None
    sql = """
        INSERT INTO log_analysis
            (detected_at, severity, summary, details, source, llm_used, sensitive, raw_content)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """
    values = (
        datetime.now(timezone.utc),
        anomaly.severity,
        anomaly.summary,
        anomaly.details,
        anomaly.source or source,
        anomaly.llm_used,
        getattr(anomaly, "sensitive", False),
        anomaly.raw_content[:2000] if anomaly.raw_content else None,
    )
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, values)
                record_id = cur.fetchone()[0]
        logger.info(f"[Aurora] log_analysis 저장: id={record_id}, severity={anomaly.severity}")
        return record_id
    except Exception as e:
        logger.error(f"[Aurora] log_analysis 저장 실패: {e}")
        return None


def save_analysis_report(report, trigger_id: int | None = None) -> int | None:
    """
    심층 분석 리포트를 analysis_report 테이블에 저장합니다.

    Args:
        report: DeepAnalysisReport 인스턴스
    Returns:
        저장된 레코드 id (실패 시 None)
    """
    if not _db_available():
        return None
    sql = """
        INSERT INTO analysis_report (created_at, trigger_id, report, model_used)
        VALUES (%s, %s, %s, %s)
        RETURNING id
    """
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (
                    datetime.now(timezone.utc),
                    trigger_id,
                    report.report,
                    report.model_used,
                ))
                record_id = cur.fetchone()[0]
        logger.info(f"[Aurora] analysis_report 저장: id={record_id}, model={report.model_used}")
        return record_id
    except Exception as e:
        logger.error(f"[Aurora] analysis_report 저장 실패: {e}")
        return None


def save_incident(cause: str) -> int | None:
    """장애 이력을 incident 테이블에 저장합니다."""
    if not _db_available():
        return None
    sql = "INSERT INTO incident (started_at, cause, status) VALUES (%s, %s, 'open') RETURNING id"
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (datetime.now(timezone.utc), cause))
                record_id = cur.fetchone()[0]
        logger.info(f"[Aurora] incident 생성: id={record_id}")
        return record_id
    except Exception as e:
        logger.error(f"[Aurora] incident 저장 실패: {e}")
        return None


def save_alert(channel: str, message: str, trigger_id: int | None = None) -> None:
    """알림 발송 이력을 alert_history 테이블에 저장합니다."""
    if not _db_available():
        return
    sql = "INSERT INTO alert_history (sent_at, channel, message, trigger_id) VALUES (%s, %s, %s, %s)"
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (datetime.now(timezone.utc), channel, message, trigger_id))
    except Exception as e:
        logger.error(f"[Aurora] alert_history 저장 실패: {e}")


def get_recent_log_analysis(limit: int = 20) -> list[dict[str, Any]]:
    """
    최근 이상 감지 이력을 반환합니다.
    Grafana Aurora 패널 + DR 시연용 쿼리와 동일한 구조.
    """
    if not _db_available():
        return []
    sql = """
        SELECT id, detected_at, severity, summary, source, llm_used, sensitive
        FROM log_analysis
        ORDER BY detected_at DESC
        LIMIT %s
    """
    try:
        with _get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, (limit,))
                rows = cur.fetchall()
        return [
            {
                **dict(row),
                "detected_at": row["detected_at"].isoformat(),
            }
            for row in rows
        ]
    except Exception as e:
        logger.error(f"[Aurora] log_analysis 조회 실패: {e}")
        return []
