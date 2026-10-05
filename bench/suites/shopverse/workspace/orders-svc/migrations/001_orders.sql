CREATE TABLE orders (id serial PRIMARY KEY, status text NOT NULL, total int NOT NULL);
CREATE TABLE order_items (id serial PRIMARY KEY, order_id int, sku text, quantity int);
CREATE TABLE refunds (id serial PRIMARY KEY, order_id int, amount int);
