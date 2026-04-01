package com.seminar.orderservice.controller;

import com.seminar.orderservice.domain.Order;
import com.seminar.orderservice.dto.OrderRequest;
import com.seminar.orderservice.dto.OrderResponse;
import com.seminar.orderservice.service.OrderService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@RestController
@RequestMapping("/api/orders")
public class OrderController {

    private final OrderService orderService;

    public OrderController(OrderService orderService) {
        this.orderService = orderService;
    }

    @PostMapping
    public ResponseEntity<?> create(@RequestBody OrderRequest request) {
        try {
            Order order = orderService.create(request);
            return ResponseEntity.ok(new OrderResponse(order));
        } catch (Exception e) {
            return ResponseEntity.internalServerError()
                    .body(Map.of("error", e.getMessage()));
        }
    }

    @GetMapping
    public List<OrderResponse> findAll() {
        return orderService.findAll().stream()
                .map(OrderResponse::new)
                .collect(Collectors.toList());
    }

    @GetMapping("/{id}")
    public ResponseEntity<?> findById(@PathVariable Long id) {
        try {
            return ResponseEntity.ok(new OrderResponse(orderService.findById(id)));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.notFound().build();
        }
    }
}
