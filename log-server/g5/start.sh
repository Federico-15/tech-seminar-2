#!/bin/bash
# 사용법: EC2_HOST=<t3.medium IP> ./start.sh
# 예)     EC2_HOST=10.0.1.23 ./start.sh

if [ -z "$EC2_HOST" ]; then
  echo "ERROR: EC2_HOST 환경변수를 설정하세요."
  echo "  예) EC2_HOST=10.0.1.23 ./start.sh"
  exit 1
fi

envsubst '${EC2_HOST}' < prometheus.yml.template > prometheus.yml
echo "prometheus.yml 생성 완료 (EC2_HOST=$EC2_HOST)"

docker compose up -d
