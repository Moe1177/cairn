CREATE TABLE "cook_profiles" (id serial PRIMARY KEY, active boolean);
CREATE TABLE "listings" (id serial PRIMARY KEY, cook_id int);
CREATE TABLE "orders" (id serial PRIMARY KEY, status text);
CREATE TABLE "users" (id serial PRIMARY KEY);
