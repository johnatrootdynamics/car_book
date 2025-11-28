CREATE TABLE IF NOT EXISTS ownerships (
  ownership_id      BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  vin               CHAR(17) NOT NULL,
  owner_user_id     BIGINT UNSIGNED NOT NULL,
  start_at          DATE NOT NULL,
  end_at            DATE NULL,
  is_primary        TINYINT(1) NOT NULL DEFAULT 1,
  acquisition_type  ENUM('purchase','lease','gift','other') DEFAULT 'purchase',
  proof_doc_url     VARCHAR(512) NULL,
  created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_own_vin FOREIGN KEY (vin) REFERENCES vehicles(vin),
  CONSTRAINT fk_own_user FOREIGN KEY (owner_user_id) REFERENCES users(user_id),
  INDEX idx_vin_dates (vin, start_at, end_at),
  INDEX idx_owner (owner_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4_unicode_520_ci;
