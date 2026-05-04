CREATE DATABASE IF NOT EXISTS carbook CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE carbook;

CREATE TABLE IF NOT EXISTS users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  first_name VARCHAR(100) NOT NULL,
  last_name VARCHAR(100) NOT NULL,
  username VARCHAR(50) NULL UNIQUE,
  email VARCHAR(255) NOT NULL UNIQUE,
  phone VARCHAR(30) NOT NULL,
  static_qr_code VARCHAR(64) NULL UNIQUE,
  date_of_birth DATE NOT NULL,
  street VARCHAR(255) NOT NULL,
  city VARCHAR(100) NOT NULL,
  state VARCHAR(100) NOT NULL,
  postal_code VARCHAR(20) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tracks (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(200) NOT NULL UNIQUE,
  city VARCHAR(100) NOT NULL,
  state VARCHAR(100) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS employees (
  id INT AUTO_INCREMENT PRIMARY KEY,
  track_id INT NOT NULL,
  full_name VARCHAR(150) NOT NULL,
  email VARCHAR(255) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_employees_track FOREIGN KEY (track_id) REFERENCES tracks(id)
    ON DELETE RESTRICT ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS enterprise_admins (
  id INT AUTO_INCREMENT PRIMARY KEY,
  full_name VARCHAR(150) NOT NULL,
  email VARCHAR(255) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cars (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  make VARCHAR(100) NOT NULL,
  model VARCHAR(100) NOT NULL,
  car_year INT NOT NULL,
  color VARCHAR(100) NULL,
  static_qr_code VARCHAR(64) NULL UNIQUE,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_cars_user FOREIGN KEY (user_id) REFERENCES users(id)
    ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS events (
  id INT AUTO_INCREMENT PRIMARY KEY,
  track_id INT NOT NULL,
  event_name VARCHAR(200) NOT NULL,
  event_date DATE NOT NULL,
  thumbnail_image_path VARCHAR(255) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_events_track FOREIGN KEY (track_id) REFERENCES tracks(id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  INDEX idx_events_track_date (track_id, event_date)
);

CREATE TABLE IF NOT EXISTS event_registrations (
  id INT AUTO_INCREMENT PRIMARY KEY,
  event_id INT NOT NULL,
  user_id INT NOT NULL,
  car_id INT NOT NULL,
  checkin_code VARCHAR(64) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_event_reg_event FOREIGN KEY (event_id) REFERENCES events(id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT fk_event_reg_user FOREIGN KEY (user_id) REFERENCES users(id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT fk_event_reg_car FOREIGN KEY (car_id) REFERENCES cars(id)
    ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT uniq_event_user_signup UNIQUE (event_id, user_id),
  INDEX idx_event_reg_user (user_id),
  INDEX idx_event_reg_car (car_id),
  INDEX idx_event_reg_checkin_code (checkin_code)
);

CREATE TABLE IF NOT EXISTS inspection_rules (
  id INT AUTO_INCREMENT PRIMARY KEY,
  track_id INT NOT NULL,
  rule_text VARCHAR(255) NOT NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  sort_order INT NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_inspection_rules_track FOREIGN KEY (track_id) REFERENCES tracks(id)
    ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS inspections (
  id INT AUTO_INCREMENT PRIMARY KEY,
  event_registration_id INT NOT NULL UNIQUE,
  inspected_by_employee_id INT NOT NULL,
  passed TINYINT(1) NOT NULL DEFAULT 0,
  notes VARCHAR(500) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_inspections_registration FOREIGN KEY (event_registration_id) REFERENCES event_registrations(id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT fk_inspections_employee FOREIGN KEY (inspected_by_employee_id) REFERENCES employees(id)
    ON DELETE RESTRICT ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS inspection_items (
  id INT AUTO_INCREMENT PRIMARY KEY,
  inspection_id INT NOT NULL,
  inspection_rule_id INT NOT NULL,
  checked TINYINT(1) NOT NULL DEFAULT 0,
  CONSTRAINT fk_inspection_items_inspection FOREIGN KEY (inspection_id) REFERENCES inspections(id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT fk_inspection_items_rule FOREIGN KEY (inspection_rule_id) REFERENCES inspection_rules(id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT uniq_inspection_rule UNIQUE (inspection_id, inspection_rule_id)
);

CREATE TABLE IF NOT EXISTS social_posts (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  event_id INT NULL,
  event_registration_id INT NULL UNIQUE,
  post_type VARCHAR(30) NOT NULL DEFAULT 'event_signup',
  title VARCHAR(200) NOT NULL,
  body VARCHAR(600) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_social_posts_user FOREIGN KEY (user_id) REFERENCES users(id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT fk_social_posts_event FOREIGN KEY (event_id) REFERENCES events(id)
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT fk_social_posts_registration FOREIGN KEY (event_registration_id) REFERENCES event_registrations(id)
    ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS social_comments (
  id INT AUTO_INCREMENT PRIMARY KEY,
  post_id INT NOT NULL,
  user_id INT NOT NULL,
  body VARCHAR(400) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_social_comments_post FOREIGN KEY (post_id) REFERENCES social_posts(id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT fk_social_comments_user FOREIGN KEY (user_id) REFERENCES users(id)
    ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS community_groups (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(120) NOT NULL UNIQUE,
  description VARCHAR(255) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS community_group_members (
  id INT AUTO_INCREMENT PRIMARY KEY,
  group_id INT NOT NULL,
  user_id INT NOT NULL,
  joined_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_group_members_group FOREIGN KEY (group_id) REFERENCES community_groups(id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT fk_group_members_user FOREIGN KEY (user_id) REFERENCES users(id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT uniq_group_member UNIQUE (group_id, user_id)
);

INSERT INTO tracks (name, city, state)
VALUES ('Demo Speedway', 'Austin', 'TX')
ON DUPLICATE KEY UPDATE name = VALUES(name);

INSERT INTO employees (track_id, full_name, email, password_hash)
SELECT t.id, 'Demo Employee', 'employee@track.local',
       'scrypt:32768:8:1$hpe5m7nSpcXe2SyA$4c1de5076c48f33169830766d0a522823db14513e9e6620a281ec39ca14fa9950a1800cca5498b97adb80d8c3f3bcd7d1fd5c2d6d2a7ecca64204a5f32ebfe41'
FROM tracks t
WHERE t.name = 'Demo Speedway'
  AND NOT EXISTS (
    SELECT 1 FROM employees e WHERE e.email = 'employee@track.local'
  );

ALTER TABLE tracks
  ADD COLUMN IF NOT EXISTS layout_image_path VARCHAR(255) NULL;
