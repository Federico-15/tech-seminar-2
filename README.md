# AI Agent Server

LLM 기반 실시간 인프라 모니터링 서버입니다.
t3 인스턴스의 order-service 로그와 Prometheus 메트릭을 수집해 이상 징후를 자동 감지하고, 심각도에 따라 Claude API / Qwen3 로컬 모델로 분석합니다.

---

## 아키텍처

```
[t3 EC2]                        [g5 EC2]
order-service                   AI Agent Server (FastAPI)
    │                               │
    ▼                               ├── Loki (로그 수집)
Fluent-bit ──── HTTP ──────────────►├── Prometheus (메트릭 수집)
(t3/fluent-bit.conf)                │
                                    ▼
                          하이브리드 LLM 라우팅
                         ┌──────────────────────┐
                         │ 일반 로그 → Claude API │
                         │ 민감 로그 → Qwen3:4B  │
                         └──────────────────────┘
                                    │
                          ┌─────────┴──────────┐
                          │ 이상 감지 시         │
                          ▼                     ▼
                       HIGH                 CRITICAL
                    Qwen3:4B              Kafka 큐 적재
                    직접 분석           → KEDA → Qwen3:8B Pod
                          │                     │
                          └─────────┬───────────┘
                                    ▼
                           Aurora PostgreSQL
                           Slack 알림
```

---

## 디렉토리 구조

```
.
├── server.py              # FastAPI 앱 + 모니터링 루프
├── agents/
│   ├── llm_router.py      # 하이브리드 LLM 라우팅 (Claude / Qwen3)
│   ├── log_monitor.py     # Loki 로그 이상 감지
│   ├── metric_monitor.py  # Prometheus 메트릭 이상 감지
│   ├── deep_analysis.py   # HIGH/CRITICAL 정밀 분석
│   ├── kafka_producer.py  # CRITICAL 이벤트 Kafka 발행
│   ├── kafka_consumer.py  # 8B Pod에서 Kafka 소비 및 분석
│   └── k8s_scaler.py      # GPU Pod 동적 스케줄링 (4B ↔ 8B)
├── config/
│   └── settings.py        # 환경변수 기반 설정 (pydantic-settings)
├── tools/
│   ├── loki_tool.py       # Loki HTTP API 클라이언트
│   └── prometheus_tool.py # Prometheus HTTP API 클라이언트
├── storage/
│   └── aurora_store.py    # Aurora PostgreSQL 저장소
├── k8s/
│   ├── keda-scaledjob.yaml    # KEDA ScaledJob (8B Pod 자동 생성)
│   ├── gpu-pod-template.yaml  # GPU 노드 Pod 템플릿
│   └── rbac-scaler.yaml       # K8s RBAC 설정
├── t3/
│   ├── fluent-bit.conf    # t3 인스턴스 Fluent-bit 설정
│   ├── parsers.conf       # JSON 로그 파서
│   └── .env.example       # t3 환경변수 예시
├── docs/
│   ├── architecture.md
│   └── how-to-run-and-test.md
├── Dockerfile
└── requirements.txt
```

---

## 실행 방법

### 1. 환경변수 설정

```bash
cp .env.example .env
# .env 파일을 열어 값 채우기
```

주요 환경변수:

| 변수 | 설명 |
|------|------|
| `LLM_PROVIDER` | `CLAUDE_API` 또는 `QWEN_LOCAL` |
| `ANTHROPIC_API_KEY` | Claude API 키 |
| `VLLM_BASE_URL` | Qwen3:4B vLLM 엔드포인트 |
| `VLLM_DEEP_URL` | Qwen3:8B vLLM 엔드포인트 |
| `LOKI_URL` | Loki 서버 주소 |
| `PROMETHEUS_URL` | Prometheus 서버 주소 |
| `AURORA_HOST` | Aurora PostgreSQL 호스트 |
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka 브로커 주소 |
| `K8S_ENABLED` | K8s GPU 스케줄링 활성화 여부 |
| `SLACK_WEBHOOK_URL` | Slack 알림 Webhook (선택) |

### 2. 패키지 설치 및 서버 실행

```bash
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8000
```

### 3. Docker 실행

```bash
docker build -t ai-agent-server .
docker run --env-file .env -p 8000:8000 ai-agent-server
```

---

## Fluent-bit 설정 (t3 인스턴스)

t3 서버에서 order-service 로그를 g5의 Loki로 전송하는 설정입니다.

```bash
cd t3
cp .env.example .env
# LOKI_HOST, LOG_PATH 설정 후:
fluent-bit -c fluent-bit.conf
```

---

## API 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| GET | `/health` | 헬스체크 |
| GET | `/status` | 모니터링 현황 조회 |
| POST | `/trigger` | 수동 분석 트리거 |
| GET | `/metrics` | Prometheus 스크랩용 메트릭 |
| GET | `/metrics/pending-jobs` | KEDA 대기 중인 CRITICAL 이벤트 수 |
| GET | `/history` | 최근 이상 감지 이력 조회 |

---

## LLM 라우팅 전략

| 조건 | 모델 | 이유 |
|------|------|------|
| `LLM_PROVIDER=QWEN_LOCAL` | Qwen3:4B (vLLM) | 전체 트래픽 로컬 처리 |
| 민감 로그 (`[PII]` 태그) | Qwen3:4B (vLLM) | 외부 유출 차단 |
| 일반 로그 + `CLAUDE_API` | Claude Sonnet | 빠른 응답 |
| CRITICAL 정밀 분석 | Qwen3:8B (vLLM) | KEDA Pod 동적 생성 후 처리 |
| HIGH 정밀 분석 | Qwen3:8B (vLLM) | 4B Pod 유지한 채 처리 |
