CREATE TABLE trips (
  id uuid PRIMARY KEY,
  rider_id uuid NOT NULL,
  driver_id uuid,
  status text NOT NULL,
  fare_cents integer NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE trip_events (id bigserial PRIMARY KEY, trip_id uuid NOT NULL, kind text NOT NULL);
