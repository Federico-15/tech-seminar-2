# 실행 및 테스트 가이드

> AI Agent Server를 처음부터 실행하고 테스트하는 방법입니다.

---

## 목차

1. [사전 준비 — 필요한 것 설치](#1-사전-준비)
2. [서버 실행](#2-서버-실행)
3. [테스트 방법 3가지](#3-테스트-방법)
4. [GitHub 연동 테스트](#4-github-연동-테스트)
5. [문제 해결](#5-문제-해결)

---

## 1. 사전 준비

### 설치해야 할 것 목록

| 도구 | 용도 | 필수 여부 |
|------|------|----------|
| Python 3.11+ | 서버 실행 언어 | 필수 |
| pip | 파이썬 패키지 설치 | 필수 |
| Semgrep | 취약점 경로 탐지 | 필수 |
| Ollama + Qwen3:30B | 로컬 AI 모델 | 선택 (없으면 Claude API 사용) |
| ngrok | 로컬 서버를 외부에 노출 (GitHub 웹훅 테스트용) | 테스트 시 필요 |

---

### Step 1. Python 설치

1. https://www.python.org/downloads/ 접속
2. "Download Python 3.12.x" 버튼 클릭
3. 설치 시 **"Add Python to PATH"** 체크박스 반드시 체크
4. 설치 완료 후 터미널에서 확인:

```bash
python --version
# 출력 예시: Python 3.12.3
```

---

### Step 2. 프로젝트 패키지 설치

터미널에서 아래 순서로 실행하세요:

```bash
# ai-agent-server 폴더로 이동
cd C:\workspace\ai-agent-server

# 필요한 파이썬 패키지 한번에 설치
pip install -r requirements.txt
```

> 설치에 1~3분 정도 걸립니다.

---

### Step 3. Semgrep 설치

```bash
pip install semgrep

# 설치 확인
semgrep --version
# 출력 예시: 1.90.0
```

---

### Step 4. 환경변수 파일 설정

```bash
# .env.example을 복사해서 .env 파일 생성
copy .env.example .env
```

`.env` 파일을 메모장으로 열어서 아래 값들을 채워주세요:

```env
# 필수: GitHub 토큰
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx

# AI 모델 설정 (둘 중 하나만 있어도 됩니다)
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxx   ← Claude API 키 (Ollama 없을 때)
OLLAMA_BASE_URL=http://localhost:11434            ← 로컬 Ollama 주소

# 선택: S3 (없으면 S3 저장만 스킵됨, 나머지는 정상 작동)
AWS_ACCESS_KEY_ID=AKIAXXXXXXXXXXXXXXXX
AWS_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxxxxxx
```

**GitHub 토큰 발급 방법:**
1. GitHub → 우측 상단 프로필 → Settings
2. 좌측 하단 Developer settings → Personal access tokens → Tokens (classic)
3. Generate new token → 체크: `repo`, `pull_requests`
4. 생성된 토큰을 `.env`에 붙여넣기

---

### Step 5. Ollama 설치 (선택 — Claude API 쓸 거면 스킵 가능)

Qwen3:30B를 로컬에서 실행하려면 필요합니다. **GPU 없어도 되지만 느립니다.**

```bash
# Ollama 설치 (Windows)
# https://ollama.com/download 에서 설치 파일 다운로드 후 실행

# 설치 후 Qwen3:30B 모델 다운로드 (약 20GB, 시간 걸림)
ollama pull qwen3:30b

# Ollama 서버 실행
ollama serve
```

> Ollama 없이 Claude API만 쓰려면 `.env`에서 `USE_FALLBACK=true` 설정

---

## 2. 서버 실행

```bash
# ai-agent-server 폴더에서 실행
cd C:\workspace\ai-agent-server

python server.py
```

정상 실행 시 아래 메시지가 뜹니다:

```
INFO:     AI Agent Server 시작
INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
```

브라우저에서 http://localhost:8080/docs 접속하면 API 문서가 보입니다.

---

## 3. 테스트 방법

### 방법 A. 가장 빠른 테스트 — curl로 헬스체크

서버가 켜진 상태에서 새 터미널을 열고:

```bash
curl http://localhost:8080/health
```

**정상 응답:**
```json
{"status": "ok", "service": "ai-agent-server"}
```

---

### 방법 B. 로컬 코드를 직접 분석해보기

실제 취약한 코드 파일을 만들어서 분석을 돌려봅니다. **GitHub 없이도 테스트 가능합니다.**

**Step 1. 테스트용 취약한 코드 파일 생성**

`C:\workspace\test-repo\app.py` 파일을 만들고 아래 내용 붙여넣기:

```python
# 일부러 취약점을 넣은 테스트 코드
import sqlite3
import subprocess

def login(username, password):
    conn = sqlite3.connect("users.db")
    # ⚠️ SQL Injection 취약점: 사용자 입력을 그대로 쿼리에 삽입
    query = f"SELECT * FROM users WHERE username='{username}' AND password='{password}'"
    cursor = conn.execute(query)
    return cursor.fetchone()

def run_command(user_input):
    # ⚠️ Command Injection 취약점: 사용자 입력을 그대로 shell에 전달
    result = subprocess.run(f"echo {user_input}", shell=True, capture_output=True)
    return result.stdout
```

**Step 2. 테스트 스크립트 실행**

```bash
# test_local.py 파일을 만들어서 실행
python test_local.py
```

`test_local.py` 파일 내용:

```python
import asyncio
import sys
sys.path.insert(0, ".")  # 현재 폴더를 패키지 경로에 추가

from agents.graph import run_vulnerability_scan

async def main():
    result = await run_vulnerability_scan(
        repo_full_name="test/repo",
        pr_number=1,
        head_sha="abc12345",
        base_sha="def67890",
        repo_path="C:/workspace/test-repo",   # 취약한 코드가 있는 폴더
    )

    print("\n===== 분석 결과 =====")
    print(f"Semgrep 발견: {len(result.get('semgrep_findings', []))}개")
    print(f"Discovery 선별: {len(result.get('filtered_paths', []))}개")
    print(f"확정 취약점: {len(result.get('vulnerabilities', []))}개")

    for v in result.get("vulnerabilities", []):
        print(f"\n[{v.get('severity')}] {v.get('title')}")
        print(f"  파일: {v.get('file')}:{v.get('line_start')}")
        print(f"  설명: {v.get('description', '')[:100]}")

asyncio.run(main())
```

**정상 출력 예시:**
```
===== 분석 결과 =====
Semgrep 발견: 5개
Discovery 선별: 2개
확정 취약점: 2개

[HIGH] SQL Injection in login function
  파일: app.py:7
  설명: 사용자 입력이 SQL 쿼리에 직접 삽입되어 공격자가 인증을 우회하거나...

[HIGH] Command Injection in run_command function
  파일: app.py:13
  설명: shell=True와 함께 사용자 입력을 그대로 전달하여...
```

---

### 방법 C. API 직접 호출 테스트

서버가 실행 중인 상태에서 `/scan` 엔드포인트를 직접 호출합니다.

```bash
curl -X POST "http://localhost:8080/scan" \
  -H "Content-Type: application/json" \
  -d '{
    "repo_full_name": "your-github-id/your-repo",
    "pr_number": 1,
    "head_sha": "커밋SHA값",
    "base_sha": "베이스SHA값"
  }'
```

**정상 응답:**
```json
{"message": "분석 시작됨", "pr_number": 1}
```

서버 터미널에서 분석 진행 로그가 출력됩니다:

```
INFO  [Pipeline] 시작: your-github-id/your-repo#1
INFO  [Discovery] Semgrep 실행: /tmp/ai-agent-xxxxx
INFO  [Discovery] Semgrep 결과: 12개
INFO  [Discovery] 선별된 위험 경로: 5개
INFO  [Analysis] 5개 경로 정밀 분석 시작
INFO  [Analysis] 확정 취약점: 3개
INFO  [Pipeline] 완료: failure (취약점 3개 발견 (HIGH: 2개) — 빌드 중단)
```

---

## 4. GitHub 연동 테스트

실제로 PR에 코멘트가 달리는 것을 테스트합니다.

### Step 1. ngrok 설치 및 실행

로컬 서버를 GitHub이 접근할 수 있도록 외부에 노출시킵니다.

```bash
# ngrok 설치: https://ngrok.com/download

# 로컬 8080 포트를 외부에 노출
ngrok http 8080
```

아래와 같은 주소가 나옵니다:
```
Forwarding  https://abc123.ngrok-free.app → http://localhost:8080
```

### Step 2. GitHub 웹훅 등록

1. 테스트할 GitHub 저장소 → Settings → Webhooks → Add webhook
2. 아래와 같이 입력:

```
Payload URL:  https://abc123.ngrok-free.app/webhook/github
Content type: application/json
Secret:       (비워두거나 .env의 GITHUB_WEBHOOK_SECRET과 동일하게)
Events:       "Let me select individual events" → Pull requests 체크
```

### Step 3. 테스트 PR 생성

저장소에 취약한 코드를 담은 브랜치를 만들어 PR을 열면, 자동으로 분석이 시작되고 PR에 코멘트가 달립니다.

**PR 코멘트 예시:**

```
## AI 취약점 분석 결과

> **3개의 취약점이 발견되었습니다.** 빌드가 중단됩니다.

| 심각도 | 위치 | 유형 | 권장 조치 |
|--------|------|------|-----------|
| 🔴 HIGH | `app.py:7` | SQL Injection | 파라미터화된 쿼리 사용 |
| 🔴 HIGH | `app.py:13` | Command Injection | shell=False 사용 |
| 🟡 MEDIUM | `app.py:20` | Path Traversal | 경로 검증 추가 |
```

---

## 5. 문제 해결

### "ModuleNotFoundError" 오류

```bash
# 패키지가 설치 안 된 경우
pip install -r requirements.txt
```

### "semgrep: command not found"

```bash
pip install semgrep

# 그래도 안 되면 경로 확인
where semgrep
```

### Ollama 연결 실패

```bash
# Ollama가 실행 중인지 확인
ollama list

# 실행 안 됐으면
ollama serve
```

Ollama 없이 Claude API만 쓰려면 `.env` 파일에서:
```env
USE_FALLBACK=true
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxx
```

### S3 오류 (저장 실패)

S3 없어도 분석은 정상 작동합니다. 로그에 아래 메시지가 뜨면 S3만 실패한 것:
```
[S3] 저장 실패 (non-fatal): ...
```

AWS 자격증명이 없으면 `.env`에서 S3 관련 항목을 비워두면 됩니다.

### 포트 충돌 (8080이 이미 사용 중)

`.env` 파일에서 포트 변경:
```env
PORT=9090
```

---

## 빠른 시작 요약

```bash
# 1. Python 설치 후
cd C:\workspace\ai-agent-server

# 2. 패키지 설치
pip install -r requirements.txt
pip install semgrep

# 3. 환경변수 설정
copy .env.example .env
# .env 열어서 GITHUB_TOKEN, ANTHROPIC_API_KEY 입력

# 4. 서버 실행
python server.py

# 5. 헬스체크
curl http://localhost:8080/health

# 6. 로컬 분석 테스트
python test_local.py
```
