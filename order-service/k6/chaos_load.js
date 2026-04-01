// 3단계: 고부하 장애 유발 시나리오 (vus: 50, sleep 없음)
import http from 'k6/http';
import { check } from 'k6';

export const options = {
  vus: 50,
  duration: '120s',
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8090';

export default function () {
  const payload = JSON.stringify({ productId: 1, quantity: 1 });
  const params = { headers: { 'Content-Type': 'application/json' } };

  const res = http.post(`${BASE_URL}/api/orders`, payload, params);
  check(res, { 'status 200': (r) => r.status === 200 });
  // sleep 없음 → 최대 부하로 커넥션 풀 고갈 유도
}
