package charge

const tripFare = "SELECT fare_cents FROM trips WHERE id = $1 AND status = 'completed'"
const insertPayment = "INSERT INTO payments (id, trip_id, amount_cents) VALUES ($1, $2, $3)"

func Charge(tripID string) error { return nil }
