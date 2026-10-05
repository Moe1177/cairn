package internal

const insertLedger = "INSERT INTO payments_ledger (id) VALUES ($1)"
const findOrder = "SELECT id FROM orders WHERE id = $1"
