CREATE TABLE IF NOT EXISTS vehicle_scores (
  vin            CHAR(17) NOT NULL,
  score          TINYINT UNSIGNED NOT NULL,
  components_json JSON NULL,
  computed_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (vin),
  CONSTRAINT fk_vs_vin FOREIGN KEY (vin) REFERENCES vehicles(vin)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4_unicode_520_ci;
