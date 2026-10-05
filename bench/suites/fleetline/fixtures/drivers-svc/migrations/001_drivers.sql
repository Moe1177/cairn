CREATE TABLE vehicles (id uuid PRIMARY KEY, plate text NOT NULL, model text);
CREATE TABLE drivers (
  id uuid PRIMARY KEY,
  name text NOT NULL,
  license_no text NOT NULL UNIQUE,
  vehicle_id uuid REFERENCES vehicles (id)
);
