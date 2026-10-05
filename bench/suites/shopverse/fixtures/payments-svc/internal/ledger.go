package internal

const insertCharge = "INSERT INTO payments_ledger (order_id, amount) VALUES ($1, $2)"
const orderStatus = "SELECT id, status FROM orders WHERE id = $1"
