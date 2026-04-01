// 1단계: 정상 부하 시나리오 (vus: 5)
import http from 'k6/http';
import { sleep, check } from 'k6';

export const options = {
  vus: 5,
  duration: '60s',
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8090';

export default function () {
  const payload = JSON.stringify({ productId: 1, quantity: 1 });
  const params = { headers: { 'Content-Type': 'application/json' } };

  const res = http.post(`${BASE_URL}/api/orders`, payload, params);
  check(res, { 'status 200': (r) => r.status === 200 });
  sleep(1);
}
