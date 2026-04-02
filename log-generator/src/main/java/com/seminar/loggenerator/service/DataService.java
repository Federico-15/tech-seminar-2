package com.seminar.loggenerator.service;

import com.seminar.loggenerator.entity.DataEntity;
import com.seminar.loggenerator.repository.DataRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class DataService {

    private static final Logger log = LoggerFactory.getLogger(DataService.class);

    private final DataRepository repository;

    public DataService(DataRepository repository) {
        this.repository = repository;
    }

    public List<DataEntity> findAll() {
        long start = System.currentTimeMillis();
        List<DataEntity> result = repository.findAll();
        long elapsed = System.currentTimeMillis() - start;
        log.info("service=api-server event=db_query rows={} elapsed={}ms", result.size(), elapsed);
        return result;
    }
}
