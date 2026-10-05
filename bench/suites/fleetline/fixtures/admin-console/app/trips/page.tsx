import { recentTrips } from "../../lib/db";

export default async function TripsPage() {
  const trips = await recentTrips();
  return <pre>{JSON.stringify(trips, null, 2)}</pre>;
}
