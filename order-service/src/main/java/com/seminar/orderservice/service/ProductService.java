package com.seminar.orderservice.service;

import com.seminar.orderservice.domain.Product;
import com.seminar.orderservice.repository.ProductRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Service
public class ProductService {

    private static final Logger log = LoggerFactory.getLogger(ProductService.class);

    private final ProductRepository productRepository;

    public ProductService(ProductRepository productRepository) {
        this.productRepository = productRepository;
    }

    @Transactional(readOnly = true)
    public List<Product> findAll() {
        List<Product> products = productRepository.findAll();
        log.info("service=product event=list_fetched count={}", products.size());
        return products;
    }

    @Transactional(readOnly = true)
    public Product findById(Long id) {
        return productRepository.findById(id)
                .orElseThrow(() -> {
                    log.error("service=product event=product_not_found productId={}", id);
                    return new IllegalArgumentException("상품을 찾을 수 없습니다 - productId: " + id);
                });
    }

    @Transactional
    public Product save(Product product) {
        Product saved = productRepository.save(product);
        log.info("service=product event=product_created productId={} name={} stock={}",
                saved.getId(), saved.getName(), saved.getStock());
        return saved;
    }
}
