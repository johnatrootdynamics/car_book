CREATE DATABASE IF NOT EXISTS racetrack CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE racetrack;

CREATE TABLE IF NOT EXISTS users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  first_name VARCHAR(100) NOT NULL,
  last_name VARCHAR(100) NOT NULL,
  email VARCHAR(255) NOT NULL UNIQUE,
  phone VARCHAR(30) NOT NULL,
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

CREATE TABLE IF NOT EXISTS cars (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  make VARCHAR(100) NOT NULL,
  model VARCHAR(100) NOT NULL,
  car_year INT NOT NULL,
  color VARCHAR(100) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_cars_user FOREIGN KEY (user_id) REFERENCES users(id)
    ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS events (
  id INT AUTO_INCREMENT PRIMARY KEY,
  track_id INT NOT NULL,
  event_name VARCHAR(200) NOT NULL,
  event_date DATE NOT NULL,
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
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_event_reg_event FOREIGN KEY (event_id) REFERENCES events(id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT fk_event_reg_user FOREIGN KEY (user_id) REFERENCES users(id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT fk_event_reg_car FOREIGN KEY (car_id) REFERENCES cars(id)
    ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT uniq_event_user_signup UNIQUE (event_id, user_id),
  INDEX idx_event_reg_user (user_id),
  INDEX idx_event_reg_car (car_id)
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
