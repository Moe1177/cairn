CREATE TABLE fares (city text PRIMARY KEY, base_cents integer NOT NULL, per_km_cents integer NOT NULL);
CREATE TABLE surge_zones (zone_id text PRIMARY KEY, multiplier numeric NOT NULL, updated_at timestamptz);
