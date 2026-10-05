package fare

const baseQuery = "SELECT base_cents, per_km_cents FROM fares WHERE city = $1"

func Base(city string, km float64) int { return 250 + int(km*120) }
