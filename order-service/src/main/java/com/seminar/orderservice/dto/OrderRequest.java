package com.seminar.orderservice.dto;

import lombok.Getter;
import lombok.NoArgsConstructor;

@Getter
@NoArgsConstructor
public class OrderRequest {
    private String customerId;
    private Long productId;
    private int quantity;
}
