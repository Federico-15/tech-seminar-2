FROM python:3.12-slim

# 시스템 패키지 설치 (Semgrep, ripgrep, git)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Semgrep 설치
RUN pip install semgrep --no-cache-dir

WORKDIR /app

# 의존성 먼저 설치 (레이어 캐싱 최적화)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 복사
COPY . .

# 비루트 사용자 실행 (보안)
RUN useradd -m -u 1000 agent && chown -R agent:agent /app
USER agent

EXPOSE 8080

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
