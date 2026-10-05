CREATE TABLE payments_ledger (id serial PRIMARY KEY, order_id int, amount int, charged_at timestamptz);
