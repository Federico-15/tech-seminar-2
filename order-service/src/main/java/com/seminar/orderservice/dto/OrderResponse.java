package com.seminar.orderservice.dto;

import com.seminar.orderservice.domain.Order;
import com.seminar.orderservice.domain.OrderStatus;
import lombok.Getter;

import java.time.LocalDateTime;

@Getter
public class OrderResponse {
    private final Long id;
    private final String customerId;
    private final Long productId;
    private final int quantity;
    private final int totalPrice;
    private final OrderStatus status;
    private final LocalDateTime createdAt;

    public OrderResponse(Order order) {
        this.id = order.getId();
        this.customerId = order.getCustomerId();
        this.productId = order.getProductId();
        this.quantity = order.getQuantity();
        this.totalPrice = order.getTotalPrice();
        this.status = order.getStatus();
        this.createdAt = order.getCreatedAt();
    }
}
