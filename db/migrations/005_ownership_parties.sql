CREATE TABLE IF NOT EXISTS ownership_parties (
  ownership_party_id  BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  ownership_id        BIGINT UNSIGNED NOT NULL,
  user_id             BIGINT UNSIGNED NOT NULL,
  role                ENUM('primary','co_owner') NOT NULL DEFAULT 'co_owner',
  share_pct           DECIMAL(5,2) NULL,
  can_edit            TINYINT(1) NOT NULL DEFAULT 1,
  created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_op_own FOREIGN KEY (ownership_id) REFERENCES ownerships(ownership_id),
  CONSTRAINT fk_op_user FOREIGN KEY (user_id) REFERENCES users(user_id),
  UNIQUE KEY uq_party (ownership_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
