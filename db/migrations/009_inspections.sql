CREATE TABLE IF NOT EXISTS inspections (
  inspection_id       BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  vin                 CHAR(17) NOT NULL,
  date                DATE NOT NULL,
  odometer            INT UNSIGNED NULL,
  unit_system         ENUM('mi','km') NOT NULL DEFAULT 'mi',
  inspection_type     ENUM('safety','emissions','pre_purchase','insurance','general','other') NOT NULL DEFAULT 'general',
  result              ENUM('pass','fail','advisory') NOT NULL DEFAULT 'advisory',
  description         TEXT NULL,
  inspected_by        VARCHAR(128) NULL,
  attachments_json    JSON NULL,
  created_by_user_id  BIGINT UNSIGNED NOT NULL,
  visibility          ENUM('public','link','private') NOT NULL DEFAULT 'public',
  created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_insp_vin FOREIGN KEY (vin) REFERENCES vehicles(vin),
  CONSTRAINT fk_insp_user FOREIGN KEY (created_by_user_id) REFERENCES users(user_id),
  INDEX idx_insp_vin_date (vin, date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
