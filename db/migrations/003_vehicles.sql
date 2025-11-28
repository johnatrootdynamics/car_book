CREATE TABLE IF NOT EXISTS vehicles (
  vin                 CHAR(17) PRIMARY KEY,
  model_year          SMALLINT NOT NULL,
  make                VARCHAR(64) NOT NULL,
  model               VARCHAR(64) NOT NULL,
  trim                VARCHAR(64) NULL,
  engine              VARCHAR(128) NULL,
  transmission        VARCHAR(64)  NULL,
  drive_type          VARCHAR(32)  NULL,
  body                VARCHAR(64)  NULL,
  color               VARCHAR(32)  NULL,
  spec_source         ENUM('stock','override') NOT NULL DEFAULT 'stock',
  overrides_json      JSON NULL,
  stock_source        VARCHAR(64) NULL,
  first_seen_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_vehicle_year_make_model (model_year, make, model)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4_unicode_520_ci;
