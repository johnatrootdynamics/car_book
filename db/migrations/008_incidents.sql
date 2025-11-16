CREATE TABLE IF NOT EXISTS incidents (
  incident_id         BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  vin                 CHAR(17) NOT NULL,
  date                DATE NOT NULL,
  odometer            INT UNSIGNED NULL,
  unit_system         ENUM('mi','km') NOT NULL DEFAULT 'mi',
  type                ENUM('accident','collision','flood','fire','theft','vandalism','salvage','other') NOT NULL DEFAULT 'other',
  severity            ENUM('minor','moderate','major','total_loss','unknown') NOT NULL DEFAULT 'unknown',
  description         TEXT NULL,
  total_cost          DECIMAL(10,2) NULL,
  currency            CHAR(3) NOT NULL DEFAULT 'USD',
  attachments_json    JSON NULL,
  created_by_user_id  BIGINT UNSIGNED NULL,
  visibility          ENUM('public','link','private') NOT NULL DEFAULT 'public',

  provider_name       VARCHAR(64) NULL,
  provider_event_id   VARCHAR(128) NULL,
  provider_first_seen_at DATETIME NULL,
  raw_payload_json    JSON NULL,

  created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  CONSTRAINT fk_inc_vin FOREIGN KEY (vin) REFERENCES vehicles(vin),

  UNIQUE KEY uq_provider_event (provider_name, provider_event_id),
  INDEX idx_inc_vin_date (vin, date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
