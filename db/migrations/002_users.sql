CREATE TABLE IF NOT EXISTS users (
  user_id           BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  first_name        VARCHAR(80) NOT NULL,
  last_name         VARCHAR(80) NOT NULL,
  username          VARCHAR(40) NOT NULL UNIQUE,
  email             VARCHAR(255) NOT NULL UNIQUE,
  phone             VARCHAR(32) NULL,
  password_hash     CHAR(60) NOT NULL,
  role              ENUM('user','moderator','admin') NOT NULL DEFAULT 'user',
  future_roles_json JSON NULL,
  created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
