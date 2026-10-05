CREATE TABLE riders (id uuid PRIMARY KEY, email text NOT NULL, phone text);
CREATE TABLE rider_ratings (rider_id uuid NOT NULL, stars integer NOT NULL);
