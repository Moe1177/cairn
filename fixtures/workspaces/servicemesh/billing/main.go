package main

import (
	"net/http"
	"os"
)

func main() {
	http.HandleFunc("/invoices", invoices)
	http.HandleFunc("/health", health)
	nc.Subscribe("trip.completed", onTrip)
	http.ListenAndServe(":"+os.Getenv("PORT"), nil)
}
