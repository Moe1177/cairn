package payout

// Weekly driver payouts: 80% of each completed trip's fare.
const driverShare = 0.8
const insertPayout = "INSERT INTO payouts (id, driver_id, amount_cents) VALUES ($1, $2, $3)"

func Amount(fareCents int) int { return int(float64(fareCents) * driverShare) }
