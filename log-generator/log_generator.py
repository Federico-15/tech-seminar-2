"""
더미 로그 생성기 (v8)

실제 서비스 없이 세미나 시연용 로그를 생성합니다.
Fluent Bit이 이 파일을 감시하여 Loki로 전송합니다.

사용법:
    python log_generator.py --mode normal    # 정상 로그
    python log_generator.py --mode chaos     # 이상 로그 (에러 폭증)
    python log_generator.py --mode sensitive # 민감 정보 포함 로그 (Qwen3 라우팅 시연)
    python log_generator.py --mode normal --interval 2 --output /var/log/app/app.log
"""
import argparse
import random
import sys
import time
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# 로그 템플릿
# ---------------------------------------------------------------------------

NORMAL_LOGS = [
    "INFO  GET /api/health 200 {ms}ms",
    "INFO  POST /api/analyze 200 {ms}ms",
    "INFO  GET /api/history 200 {ms}ms",
    "INFO  AI analysis started job_id={job}",
    "INFO  AI analysis completed job_id={job} duration={ms}ms",
    "INFO  Prometheus metrics collected cpu={cpu}% memory={mem}%",
    "INFO  Loki logs fetched count={count}",
    "INFO  Aurora query OK rows={rows} duration={ms}ms",
    "WARN  Response time {ms}ms exceeded 2000ms threshold",
    "WARN  Queue depth {depth} approaching limit",
]

CHAOS_LOGS = [
    "ERROR POST /api/analyze 500 internal server error",
    "ERROR DB connection timeout after 30s host=aurora-primary",
    "ERROR POST /api/analyze 500 internal server error",
    "ERROR Queue processing failed: max retries exceeded",
    "ERROR DB connection timeout after 30s host=aurora-primary",
    "ERROR POST /api/analyze 500 internal server error",
    "WARN  Response time {ms}ms exceeded 5000ms threshold",
    "ERROR LLM API call failed: connection reset by peer",
    "ERROR POST /api/analyze 500 internal server error",
    "ERROR DB connection pool exhausted max_connections=20",
    "ERROR POST /api/analyze 503 service unavailable",
    "WARN  Memory usage {mem}% critical threshold reached",
    "ERROR Failed to save analysis result to Aurora",
    "ERROR Loki query failed: context deadline exceeded",
]

SENSITIVE_LOGS = [
    "ERROR Auth failed for user email=hong@company.com attempt=3",
    "WARN  Invalid token=eyJhbGciOiJIUzI1NiJ9.xxx detected from 192.168.1.45",
    "ERROR password validation failed user_id=1042 ip=10.0.1.23",
    "WARN  Suspicious login api_key=sk-internal-xxxx source=external",
    "ERROR Connection refused from internal service 192.168.1.45:5432",
    "WARN  Secret rotation required for secret_name=db-password",
    "ERROR JWT token expired email=admin@company.com session_id=abc123",
    "WARN  Rate limit exceeded for api_key=prod-key-001 ip=10.0.2.15",
]


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _render(template: str) -> str:
    return template.format(
        ms=random.randint(10, 8000),
        job=f"job-{random.randint(1000, 9999)}",
        cpu=random.randint(40, 98),
        mem=random.randint(50, 95),
        count=random.randint(10, 200),
        rows=random.randint(1, 50),
        depth=random.randint(80, 150),
    )


def generate_log(mode: str) -> str:
    ts = _timestamp()
    if mode == "normal":
        line = _render(random.choice(NORMAL_LOGS))
    elif mode == "chaos":
        pool = CHAOS_LOGS * 3 + NORMAL_LOGS  # 에러 비율 높임
        line = _render(random.choice(pool))
    elif mode == "sensitive":
        pool = SENSITIVE_LOGS * 2 + CHAOS_LOGS
        line = random.choice(pool)
    else:
        line = _render(random.choice(NORMAL_LOGS))
    return f"{ts} {line}"


def main():
    parser = argparse.ArgumentParser(description="더미 로그 생성기")
    parser.add_argument(
        "--mode",
        choices=["normal", "chaos", "sensitive"],
        default="normal",
        help="생성 모드 (기본값: normal)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="로그 생성 간격(초) (기본값: 1.0)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="출력 파일 경로 (기본값: stdout)",
    )
    args = parser.parse_args()

    output = open(args.output, "a", buffering=1) if args.output else sys.stdout

    print(f"[LogGenerator] 시작: mode={args.mode}, interval={args.interval}s", flush=True)
    try:
        while True:
            line = generate_log(args.mode)
            print(line, file=output, flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[LogGenerator] 종료", flush=True)
    finally:
        if args.output:
            output.close()


if __name__ == "__main__":
    main()
