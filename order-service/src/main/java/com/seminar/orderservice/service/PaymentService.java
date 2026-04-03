package com.seminar.orderservice.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

@Service
public class PaymentService {

    private static final Logger log = LoggerFactory.getLogger(PaymentService.class);
    private static final int PAYMENT_DELAY_MS = 50;

    public void process(Long orderId, int amount) {
        long start = System.currentTimeMillis();
        try {
            // 외부 결제 API 흉내 (Chaos Monkey가 이 호출을 공격)
            Thread.sleep(PAYMENT_DELAY_MS);
            long elapsed = System.currentTimeMillis() - start;
            log.info("service=payment event=payment_completed orderId={} amount={} elapsed={}ms",
                    orderId, amount, elapsed);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            long elapsed = System.currentTimeMillis() - start;
            log.error("service=payment event=payment_failed orderId={} elapsed={}ms error=\"{}\"",
                    orderId, elapsed, e.getMessage());
            throw new RuntimeException("결제 처리 실패 - orderId: " + orderId);
        }
    }
}