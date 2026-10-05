CREATE TABLE payments (id uuid PRIMARY KEY, trip_id uuid NOT NULL, amount_cents integer NOT NULL);
CREATE TABLE payouts (id uuid PRIMARY KEY, driver_id uuid NOT NULL, amount_cents integer NOT NULL, paid_at timestamptz);
