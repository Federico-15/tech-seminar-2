package com.seminar.loggenerator.controller;

import com.seminar.loggenerator.entity.DataEntity;
import com.seminar.loggenerator.service.DataService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api")
public class ApiController {

    private static final Logger log = LoggerFactory.getLogger(ApiController.class);

    private final DataService dataService;

    public ApiController(DataService dataService) {
        this.dataService = dataService;
    }

    @GetMapping("/health")
    public Map<String, String> health() {
        log.info("service=api-server event=health_check status=OK");
        return Map.of("status", "ok", "service", "log-generator");
    }

    @GetMapping("/data")
    public ResponseEntity<?> getData() {
        long start = System.currentTimeMillis();
        try {
            List<DataEntity> result = dataService.findAll();
            long elapsed = System.currentTimeMillis() - start;
            log.info("service=api-server event=request_completed method=GET path=/api/data status=200 elapsed={}ms", elapsed);
            return ResponseEntity.ok(result);
        } catch (Exception e) {
            long elapsed = System.currentTimeMillis() - start;
            log.error("service=api-server event=request_failed method=GET path=/api/data status=500 elapsed={}ms error=\"{}\"",
                    elapsed, e.getMessage());
            return ResponseEntity.internalServerError()
                    .body(Map.of("error", e.getMessage()));
        }
    }
}
