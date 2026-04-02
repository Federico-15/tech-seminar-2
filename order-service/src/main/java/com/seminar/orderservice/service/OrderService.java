package com.seminar.orderservice.service;

import com.seminar.orderservice.domain.Order;
import com.seminar.orderservice.domain.OrderItem;
import com.seminar.orderservice.domain.Product;
import com.seminar.orderservice.dto.OrderRequest;
import com.seminar.orderservice.repository.OrderItemRepository;
import com.seminar.orderservice.repository.OrderRepository;
import com.seminar.orderservice.repository.ProductRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Service
public class OrderService {

    private static final Logger log = LoggerFactory.getLogger(OrderService.class);

    private final OrderRepository orderRepository;
    private final OrderItemRepository orderItemRepository;
    private final ProductRepository productRepository;
    private final PaymentService paymentService;
    private final NotificationService notificationService;

    public OrderService(OrderRepository orderRepository,
                        OrderItemRepository orderItemRepository,
                        ProductRepository productRepository,
                        PaymentService paymentService,
                        NotificationService notificationService) {
        this.orderRepository = orderRepository;
        this.orderItemRepository = orderItemRepository;
        this.productRepository = productRepository;
        this.paymentService = paymentService;
        this.notificationService = notificationService;
    }

    @Transactional
    public Order create(OrderRequest request) {
        long start = System.currentTimeMillis();
        if (request.getCustomerId() != null) {
            MDC.put("customerId", request.getCustomerId());
            MDC.put("pii", "[PII]");
        }
        log.info("service=order event=order_received customerId={} productId={} quantity={}",
                request.getCustomerId(), request.getProductId(), request.getQuantity());

        Order order = null;
        try {
            // 1단계: 상품 조회
            Product product = productRepository.findById(request.getProductId())
                    .orElseThrow(() -> new IllegalArgumentException("상품을 찾을 수 없습니다 - productId: " + request.getProductId()));

            // 2단계: 재고 확인
            log.info("service=order event=stock_checked productId={} stock={} requested={}",
                    product.getId(), product.getStock(), request.getQuantity());

            // 3단계: 주문 생성 (PENDING)
            int totalPrice = product.getPrice() * request.getQuantity();
            order = orderRepository.save(new Order(request.getCustomerId(), product.getId(), request.getQuantity(), totalPrice));

            // 4단계: 결제 처리
            paymentService.process(order.getId(), totalPrice);

            // 5단계: 재고 차감
            product.decreaseStock(request.getQuantity());
            productRepository.save(product);
            log.info("service=order event=stock_decreased productId={} remainingStock={}",
                    product.getId(), product.getStock());

            // 6단계: 주문 상세 저장
            orderItemRepository.save(new OrderItem(order.getId(), product.getName(), request.getQuantity(), product.getPrice()));

            // 7단계: 주문 완료
            order.complete();
            orderRepository.save(order);

            long elapsed = System.currentTimeMillis() - start;
            log.info("service=order event=order_completed orderId={} totalPrice={} elapsed={}ms",
                    order.getId(), totalPrice, elapsed);

            // 8단계: 알림 발송
            notificationService.send(order.getId());

            return order;

        } catch (Exception e) {
            long elapsed = System.currentTimeMillis() - start;
            if (order != null) {
                order.fail();
                orderRepository.save(order);
                log.error("service=order event=order_failed orderId={} elapsed={}ms error=\"{}\"",
                        order.getId(), elapsed, e.getMessage());
            } else {
                log.error("service=order event=order_failed orderId=null elapsed={}ms error=\"{}\"",
                        elapsed, e.getMessage());
            }
            throw e;
        } finally {
            MDC.clear();
        }
    }

    @Transactional(readOnly = true)
    public List<Order> findAll() {
        long start = System.currentTimeMillis();
        List<Order> orders = orderRepository.findAll();
        log.info("service=order event=orders_queried count={} elapsed={}ms",
                orders.size(), System.currentTimeMillis() - start);
        return orders;
    }

    @Transactional(readOnly = true)
    public Order findById(Long id) {
        long start = System.currentTimeMillis();
        Order order = orderRepository.findById(id)
                .orElseThrow(() -> new IllegalArgumentException("주문을 찾을 수 없습니다 - orderId: " + id));
        if (order.getCustomerId() != null) {
            MDC.put("customerId", order.getCustomerId());
            MDC.put("pii", "[PII]");
        }
        log.info("service=order event=order_queried orderId={} customerId={} status={} elapsed={}ms",
                order.getId(), order.getCustomerId(), order.getStatus(), System.currentTimeMillis() - start);
        MDC.clear();
        return order;
    }
}
