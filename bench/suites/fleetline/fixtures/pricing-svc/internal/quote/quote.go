package quote

import (
	"github.com/fleetline/pricing/internal/fare"
	"github.com/fleetline/pricing/internal/surge"
)

func Serve() {}

func Quote(city, zone string, km float64) int {
	return int(float64(fare.Base(city, km)) * surge.Multiplier(zone))
}
