# AI Agent Server 구조 설명

> 소스코드 정적 취약점 분석 서버 — 코드를 잘 모르는 분을 위한 설명서

---

## 1. 이 서버가 하는 일

개발자가 GitHub에 코드를 올리면(PR 생성), AI가 자동으로 보안 취약점을 찾아서 PR에 코멘트를 남겨줍니다.

```
개발자가 코드 Push/PR 생성
        ↓
AI Agent Server 자동 실행
        ↓
취약점 분석
        ↓
PR에 자동 코멘트 작성 + S3에 결과 저장
        ↓
취약점 있으면 빌드 중단 / 없으면 통과
```

---

## 2. 전체 구조 한눈에 보기

```
ai-agent-server/
│
├── server.py                      ← 접수 창구 (GitHub 신호 받는 곳)
│
├── agents/                        ← 두뇌 (AI가 분석하는 곳)
│   ├── graph.py                   ← 에이전트 연결 설계도
│   ├── state.py                   ← 에이전트 간 공유 데이터
│   ├── supervisor.py              ← 팀장 (흐름 조율)
│   ├── discovery.py               ← 1차 조사관 (의심 코드 수집·필터링)
│   ├── analysis.py                ← 정밀 분석관 (깊은 취약점 분석)
│   └── llm.py                     ← AI 호출 담당
│
├── tools/                         ← 도구함
│   ├── semgrep_tool.py            ← 취약한 코드 경로 탐지
│   ├── code_explorer.py           ← 코드 내용 읽기
│   └── github_tool.py             ← GitHub 코멘트·저장소 클론
│
├── storage/
│   └── s3_store.py                ← 분석 결과 S3 저장
│
├── config/
│   └── settings.py                ← 환경 설정 (API 키 등)
│
├── k8s/                           ← 쿠버네티스 설정
│   ├── agent-job.yaml             ← 이벤트 기반 Pod 생성/삭제
│   └── keda-scaledjob.yaml        ← 자동 스케일링
│
├── .github/workflows/
│   └── ai-scan.yml                ← GitHub Actions 트리거
│
├── Dockerfile                     ← 컨테이너 빌드 설정
├── requirements.txt               ← 파이썬 패키지 목록
└── .env.example                   ← 환경변수 예시
```

---

## 3. 파일별 역할 상세 설명

### 3-1. `server.py` — 접수 창구

GitHub에서 "PR이 생겼어요"라는 HTTP 신호를 받는 곳입니다.

**하는 일:**
- `/webhook/github` : GitHub 웹훅 수신 (자동 트리거)
- `/scan` : GitHub Actions에서 직접 호출
- `/health` : 서버 정상 작동 확인용

**동작 방식:**

```
GitHub 신호 수신
    ↓
서명 검증 (보안 — 진짜 GitHub에서 온 요청인지 확인)
    ↓
"분석 접수했습니다" 즉시 응답
    ↓
백그라운드에서 분석 파이프라인 실행
    ↓
① 저장소 클론 → ② AI 분석 → ③ S3 저장 → ④ PR 코멘트 → ⑤ 커밋 상태 업데이트
```

---

### 3-2. `agents/` — 두뇌 (LangGraph Multi-Agent)

3개의 AI 에이전트가 팀으로 협력합니다. **비용 최적화**가 핵심 설계 목표입니다.

#### 왜 3개로 나눴나?

> Semgrep이 찾은 취약점 후보 100개를 전부 LLM에 넣으면 비용이 매우 비쌉니다.
> Discovery가 먼저 10개로 줄여주면, Analysis는 10개만 정밀 분석하면 됩니다.

```
Semgrep 결과 100개
       ↓
  Discovery (LLM)
  → "진짜 위험한 것" 10개 선별
       ↓
  Analysis (LLM)
  → 10개 정밀 분석
       ↓
  확정 취약점 목록
```

---

#### `graph.py` — 에이전트 연결 설계도

세 에이전트가 어떤 순서로 실행되는지 정의합니다.

```
시작
 ↓
Supervisor (팀장) ──→ Discovery (1차 조사) ──┐
      ↑                                      │
      └────────────────────────────────────── ┘
      ↓
Supervisor ──→ Analysis (정밀 분석) ──┐
      ↑                               │
      └────────────────────────────── ┘
      ↓
     완료
```

- 각 에이전트가 작업을 마치면 Supervisor로 돌아옵니다.
- Supervisor가 "다음엔 뭘 해야 하나" 판단해서 다음 에이전트를 지정합니다.

---

#### `state.py` — 공유 데이터 보관함

에이전트들이 서로 데이터를 주고받을 때 사용하는 공유 공간입니다.

| 항목 | 설명 |
|------|------|
| `repo_full_name` | 분석할 저장소 이름 (예: `owner/repo`) |
| `pr_number` | PR 번호 |
| `head_sha` | 분석할 커밋 ID |
| `semgrep_findings` | Semgrep이 찾은 전체 결과 (최대 100개) |
| `filtered_paths` | Discovery가 선별한 위험 경로 (최대 10개) |
| `vulnerabilities` | Analysis가 확정한 최종 취약점 목록 |
| `next` | 다음에 실행할 에이전트 이름 |
| `error` | 오류 정보 |

---

#### `supervisor.py` — 팀장

현재 상태를 보고 다음에 누가 일해야 하는지 결정합니다.

```
Semgrep 결과 없음?  → Discovery 실행 지시
Discovery 완료?     → Analysis 실행 지시
Analysis 완료?      → 작업 종료
오류 발생?          → 즉시 종료
```

코드를 직접 쓰지 않고, **판단만** 합니다.

---

#### `discovery.py` — 1차 조사관

**역할:** Semgrep 실행 → LLM으로 위험 경로 필터링

**순서:**
1. Semgrep을 실행해서 취약점 후보 수집 (최대 100개)
2. 각 후보에 주변 코드(±5줄)를 붙여서 LLM에 전달
3. LLM이 "실제로 위험한 것" 상위 10개를 선별해 반환

**선별 기준 (LLM에 지시하는 내용):**
- SQL Injection, Command Injection, XSS, Path Traversal 등 즉각적인 위협
- 실제 사용자 입력이 위험한 함수까지 전달되는 경로
- 인증·인가 우회 가능성
- 민감 데이터 노출

> **LLM 실패 시 폴백:** LLM 호출에 실패하면 심각도(HIGH → MEDIUM → LOW) 순으로 자동 정렬해서 10개를 선택합니다.

---

#### `analysis.py` — 정밀 분석관

**역할:** Discovery가 선별한 10개를 깊이 분석

**Discovery와의 차이점:**

| | Discovery | Analysis |
|---|---|---|
| 목적 | 빠르게 걸러내기 | 깊이 파고들기 |
| 처리 수 | 100개 → 10개 | 10개 |
| 코드 컨텍스트 | ±5줄 | ±15줄 + import 목록 |
| 출력 | 위험 경로 목록 | 공격 시나리오 + 수정 코드 포함 |

**분석 결과에 포함되는 내용:**
- 취약점 제목 및 상세 설명
- 공격자가 어떻게 악용하는지 단계별 시나리오
- 취약한 코드 스니펫
- 수정 방법 및 권장 코드 예시
- CWE, OWASP 분류
- CVSS 점수

---

#### `llm.py` — AI 호출 담당

LLM을 호출하는 공통 모듈입니다. **Qwen3:30B를 먼저 시도하고, 실패하면 Claude Sonnet으로 자동 전환**합니다.

```
Qwen3:30B (Ollama, 로컬) 호출 시도
        ↓ 실패 시
Claude Sonnet (Anthropic API) 폴백
```

**왜 Qwen3:30B를 먼저 쓰나?**
로컬에서 실행하므로 API 비용이 없습니다. 분석량이 많을수록 비용 차이가 커집니다.

---

### 3-3. `tools/` — 도구함

에이전트들이 직접 사용하는 실용 도구들입니다.

#### `semgrep_tool.py`

Semgrep 정적 분석 도구를 파이썬에서 실행하는 래퍼입니다.

- OWASP Top 10, SQL Injection, XSS, Command Injection 등 7개 룰셋 적용
- 결과를 파이썬 딕셔너리 형태로 가공해서 반환
- PR 변경 파일 목록 추출 기능 포함

#### `code_explorer.py`

코드 파일을 읽고 탐색하는 도구입니다.

| 함수 | 하는 일 |
|------|---------|
| `get_file_context()` | 특정 줄 주변 코드를 라인 번호와 함께 반환 |
| `search_function_definition()` | 함수 정의를 ripgrep으로 검색 |
| `search_sink_usages()` | `execute()`, `eval()`, `os.system()` 등 위험 함수 사용처 검색 |
| `get_file_imports()` | 파일 상단의 import 목록 반환 |

#### `github_tool.py`

GitHub API와 통신하는 도구입니다.

| 함수 | 하는 일 |
|------|---------|
| `clone_pr_branch()` | PR 브랜치를 로컬에 다운로드 |
| `post_pr_summary_comment()` | 취약점 분석 결과를 PR 코멘트로 작성 |
| `set_commit_status()` | 커밋 상태를 `success` / `failure` / `pending`으로 설정 |

---

### 3-4. `storage/s3_store.py` — 기록 보관소

분석 결과를 AWS S3에 JSON 파일로 저장합니다.

**저장 경로 규칙:**
```
s3://버킷명/analysis/owner_repo/pr-123/20250329-143022-abc12345.json
```

**저장 내용:**
```
{
  "metadata": { 저장소, PR 번호, 분석 시각 },
  "summary":  { 총 Semgrep 결과 수, 확정 취약점 수, 심각도별 개수 },
  "semgrep_raw": [ Semgrep 원본 결과 전체 ],
  "vulnerabilities": [ 최종 확정 취약점 목록 ]
}
```

**왜 S3에 저장하나?**
- "이 취약점이 언제 처음 생겼지?" 추적 가능
- 반복 등장하는 취약점 패턴 분석
- 팀 전체가 이력 열람 가능

---

### 3-5. `config/settings.py` — 설정판

`.env` 파일에서 설정값을 읽어오는 곳입니다. API 키 같은 민감한 정보를 코드 안에 직접 넣지 않기 위해 분리했습니다.

| 설정 항목 | 설명 | 기본값 |
|-----------|------|--------|
| `GITHUB_TOKEN` | GitHub API 인증 토큰 | 필수 |
| `ANTHROPIC_API_KEY` | Claude API 키 (폴백용) | 선택 |
| `OLLAMA_BASE_URL` | Qwen3:30B 서버 주소 | `http://localhost:11434` |
| `S3_BUCKET` | 분석 결과 저장 버킷 | `ai-agent-analysis-results` |
| `DISCOVERY_TOP_N` | Discovery → Analysis 전달 경로 수 | `10` |

---

### 3-6. `k8s/` — 쿠버네티스 설정

**핵심 아이디어:** PR이 생길 때만 서버를 켜고, 분석이 끝나면 끕니다.

```
PR 없음  →  Pod 0개 (비용 0)
PR 생성  →  Pod 자동 생성
분석 완료 →  Pod 자동 삭제
```

| 파일 | 역할 |
|------|------|
| `agent-job.yaml` | 분석 1회 실행용 K8s Job 템플릿 |
| `keda-scaledjob.yaml` | 이벤트 기반 자동 스케일링 (KEDA) + 모델 캐시 PVC |

**Qwen3:30B 콜드 스타트 해결:**
모델 파일(약 60GB)을 매번 다운로드하면 수 분이 걸립니다. PVC(영구 볼륨)에 미리 저장해두고 Pod들이 공유 읽기로 마운트합니다.

---

### 3-7. `.github/workflows/ai-scan.yml` — GitHub Actions

PR 이벤트 발생 시 자동으로 AI Agent Server를 호출하는 자동화 스크립트입니다.

```
PR 생성/업데이트
      ↓
GitHub Actions 실행
      ↓
AI Agent Server /scan 호출
      ↓
커밋 상태 폴링 (15초마다, 최대 10분)
      ↓
success → 파이프라인 통과
failure → 빌드 중단 (PR 코멘트 확인)
```

---

## 4. AI 모델 호출 흐름

```
Discovery / Analysis 에이전트
         ↓
      llm.py
         ↓
  ┌──────────────────────────────┐
  │  1순위: Qwen3:30B (Ollama)  │  ← 로컬, 비용 없음
  │         ↓ 실패 시            │
  │  2순위: Claude Sonnet API   │  ← 클라우드, 비용 발생
  └──────────────────────────────┘
         ↓
   JSON 형식으로 응답 파싱
```

---

## 5. 비용 최적화 포인트

문서(architecture_v2.docx)에서 제시한 비용 절감 전략이 코드에 반영된 부분입니다.

| 전략 | 구현 위치 | 효과 |
|------|-----------|------|
| 100개 → 10개 필터링 | `discovery.py` | LLM 토큰 90% 절감 |
| Qwen3:30B 로컬 우선 | `llm.py` | Claude API 비용 절감 |
| 이벤트 기반 Pod 생성/삭제 | `k8s/` | 유휴 시 GPU 비용 0 |
| 모델 파일 PVC 캐싱 | `keda-scaledjob.yaml` | 콜드 스타트 방지 |

---

## 6. 시작 방법

```bash
# 1. 패키지 설치
pip install -r requirements.txt

# 2. 환경변수 설정
cp .env.example .env
# .env 파일을 열어서 GITHUB_TOKEN 등 입력

# 3. 서버 실행
python server.py
# → http://localhost:8080 에서 실행됨
```

**GitHub 웹훅 설정:**
1. GitHub 저장소 → Settings → Webhooks → Add webhook
2. Payload URL: `http://서버주소:8080/webhook/github`
3. Content type: `application/json`
4. Events: `Pull requests` 선택
