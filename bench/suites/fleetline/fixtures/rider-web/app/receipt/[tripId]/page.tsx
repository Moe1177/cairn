import type { Trip } from "@fleetline/api-types";
import { getTrip } from "../../../lib/api";
import { formatCents } from "../../../lib/money";

export default async function ReceiptPage({ params }: { params: { tripId: string } }) {
  const trip: Trip = await getTrip(params.tripId);
  return (
    <section>
      <h1>Your trip</h1>
      <p>Status: {trip.status}</p>
      <p>Fare: {formatCents(trip.fare_cents)}</p>
    </section>
  );
}
