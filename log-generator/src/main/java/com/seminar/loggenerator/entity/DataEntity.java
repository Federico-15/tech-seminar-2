package com.seminar.loggenerator.entity;

import jakarta.persistence.*;

@Entity
@Table(name = "data")
public class DataEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private String name;
    private String value;

    public DataEntity() {}

    public DataEntity(String name, String value) {
        this.name = name;
        this.value = value;
    }

    public Long getId() { return id; }
    public String getName() { return name; }
    public String getValue() { return value; }
}
