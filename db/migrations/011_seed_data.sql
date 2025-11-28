-- 011_seed_data.sql
-- Inserts one sample user, vehicle, ownership, service event, incident, and vehicle score.

INSERT INTO users (first_name, last_name, username, email, phone, password_hash, role)
VALUES (
  'Sample',
  'Driver',
  'sampledriver',
  'sampledriver@example.com',
  '555-000-0000',
  '$2b$12$X2PHJi4hd8h1UTZL5O9sXeZrj12DUu2GaMnFGXA0d0ejfqmVUzx6W',
  'user'
);

SET @sample_user_id := LAST_INSERT_ID();

INSERT INTO vehicles (
  vin, model_year, make, model, trim, engine, transmission, drive_type, body, color,
  spec_source, overrides_json, stock_source, first_seen_at
) VALUES (
  'WBAEV53412KM12345',
  2002,
  'BMW',
  '330Ci',
  'Sport',
  '3.0L I6',
  '5MT',
  'RWD',
  'Coupe',
  'Silver',
  'stock',
  NULL,
  'seed',
  NOW()
);

INSERT INTO ownerships (
  vin,
  owner_user_id,
  start_at,
  end_at,
  is_primary,
  acquisition_type,
  proof_doc_url,
  created_at
) VALUES (
  'WBAEV53412KM12345',
  @sample_user_id,
  '2020-01-01',
  NULL,
  1,
  'purchase',
  NULL,
  NOW()
);

INSERT INTO service_events (
  vin,
  date,
  odometer,
  unit_system,
  service_type,
  description,
  total_cost,
  currency,
  shop_id,
  attachments_json,
  created_by_user_id,
  visibility,
  created_at,
  updated_at
) VALUES (
  'WBAEV53412KM12345',
  '2024-06-15',
  120000,
  'mi',
  'oil',
  'Oil and filter change; cabin filter replaced.',
  89.99,
  'USD',
  NULL,
  NULL,
  @sample_user_id,
  'public',
  NOW(),
  NOW()
);

INSERT INTO incidents (
  vin,
  date,
  odometer,
  unit_system,
  type,
  severity,
  description,
  total_cost,
  currency,
  attachments_json,
  created_by_user_id,
  visibility,
  provider_name,
  provider_event_id,
  provider_first_seen_at,
  raw_payload_json,
  created_at,
  updated_at
) VALUES (
  'WBAEV53412KM12345',
  '2023-03-10',
  110000,
  'mi',
  'collision',
  'minor',
  'Minor rear bumper collision; bumper cover repainted.',
  650.00,
  'USD',
  NULL,
  @sample_user_id,
  'public',
  NULL,
  NULL,
  NULL,
  NULL,
  NOW(),
  NOW()
);

INSERT INTO vehicle_scores (
  vin,
  score,
  components_json,
  computed_at
) VALUES (
  'WBAEV53412KM12345',
  82,
  '{"maintenance": 25, "inspections": 10, "incidents": -5, "mileage": -3, "ownership": 5}',
  NOW()
);
