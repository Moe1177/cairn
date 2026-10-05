CREATE TABLE orders (id serial PRIMARY KEY);
CREATE TABLE order_items (id serial PRIMARY KEY, order_id int);
