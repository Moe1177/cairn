package surge

const zoneQuery = "SELECT multiplier FROM surge_zones WHERE zone_id = $1"

// Multiplier returns the demand multiplier for a zone, capped at 3x.
func Multiplier(zone string) float64 {
	m := lookup(zone)
	if m > 3.0 {
		return 3.0
	}
	return m
}

func lookup(zone string) float64 { return 1.0 }
