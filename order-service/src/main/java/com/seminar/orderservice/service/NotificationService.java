package com.seminar.orderservice.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

@Service
public class NotificationService {

    private static final Logger log = LoggerFactory.getLogger(NotificationService.class);
    private static final int NOTIFICATION_DELAY_MS = 20;

    public void send(Long orderId) {
        long start = System.currentTimeMillis();
        try {
            // Slack 알림 흉내 (Chaos Monkey가 이 호출을 공격)
            Thread.sleep(NOTIFICATION_DELAY_MS);
            long elapsed = System.currentTimeMillis() - start;
            log.info("service=notification event=notification_sent orderId={} elapsed={}ms",
                    orderId, elapsed);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            long elapsed = System.currentTimeMillis() - start;
            log.warn("service=notification event=notification_failed orderId={} elapsed={}ms error=\"{}\"",
                    orderId, elapsed, e.getMessage());
            // 알림 실패는 주문에 영향 없음
        }
    }
}
