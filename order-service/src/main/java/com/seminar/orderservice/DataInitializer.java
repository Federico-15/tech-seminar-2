package com.seminar.orderservice;

import com.seminar.orderservice.domain.Product;
import com.seminar.orderservice.repository.ProductRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;

@Component
public class DataInitializer implements ApplicationRunner {

    private static final Logger log = LoggerFactory.getLogger(DataInitializer.class);

    private final ProductRepository productRepository;

    public DataInitializer(ProductRepository productRepository) {
        this.productRepository = productRepository;
    }

    @Override
    public void run(ApplicationArguments args) {
        if (productRepository.count() == 0) {
            productRepository.save(new Product("노트북", 1500000, 100));
            productRepository.save(new Product("마우스", 30000, 500));
            productRepository.save(new Product("키보드", 80000, 300));
            log.info("service=order-service event=data_initialized message=\"초기 상품 데이터 생성 완료\"");
        }
    }
}
