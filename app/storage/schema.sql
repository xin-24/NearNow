CREATE TABLE IF NOT EXISTS users (
  user_id VARCHAR(64) PRIMARY KEY,
  username VARCHAR(120) NOT NULL UNIQUE,
  display_name VARCHAR(120) NOT NULL,
  password_hash VARCHAR(256) NOT NULL,
  password_salt VARCHAR(128) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS app_sessions (
  token_hash VARCHAR(128) PRIMARY KEY,
  user_id VARCHAR(64) NOT NULL,
  expires_at DATETIME NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_app_sessions_user_id (user_id),
  INDEX idx_app_sessions_expires_at (expires_at),
  CONSTRAINT fk_app_sessions_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_locations (
  location_id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id VARCHAR(64) NOT NULL,
  home_location VARCHAR(255),
  city VARCHAR(120),
  district VARCHAR(120),
  landmark VARCHAR(255),
  formatted_address VARCHAR(255),
  lat DECIMAL(10, 7),
  lng DECIMAL(10, 7),
  location_source VARCHAR(40),
  accuracy_m DECIMAL(10, 2),
  precision_value VARCHAR(60),
  address_source VARCHAR(80),
  address_confidence VARCHAR(40),
  raw_json JSON,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_user_locations_user_id (user_id),
  CONSTRAINT fk_user_locations_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS planning_records (
  plan_id VARCHAR(64) PRIMARY KEY,
  user_id VARCHAR(64) NOT NULL,
  mode VARCHAR(24) NOT NULL,
  message TEXT NOT NULL,
  user_context_json JSON NOT NULL,
  plan_json JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_planning_records_user_id (user_id),
  CONSTRAINT fk_planning_records_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS companions (
  companion_id VARCHAR(64) PRIMARY KEY,
  user_id VARCHAR(64) NOT NULL,
  name VARCHAR(120) NOT NULL,
  relation VARCHAR(80),
  contact_method VARCHAR(40),
  contact_value VARCHAR(160),
  note VARCHAR(255),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uniq_user_companion_contact (user_id, name, contact_method, contact_value),
  INDEX idx_companions_user_id (user_id),
  CONSTRAINT fk_companions_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS plan_notifications (
  notification_id BIGINT AUTO_INCREMENT PRIMARY KEY,
  plan_id VARCHAR(64) NOT NULL,
  user_id VARCHAR(64) NOT NULL,
  companion_id VARCHAR(64),
  recipient_name VARCHAR(120) NOT NULL,
  relation VARCHAR(80),
  contact_method VARCHAR(40),
  contact_value VARCHAR(160),
  message TEXT,
  status VARCHAR(40) NOT NULL DEFAULT 'pending',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_plan_notifications_plan_id (plan_id),
  INDEX idx_plan_notifications_user_id (user_id),
  CONSTRAINT fk_plan_notifications_plan FOREIGN KEY (plan_id) REFERENCES planning_records(plan_id) ON DELETE CASCADE,
  CONSTRAINT fk_plan_notifications_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
  CONSTRAINT fk_plan_notifications_companion FOREIGN KEY (companion_id) REFERENCES companions(companion_id) ON DELETE SET NULL
);
