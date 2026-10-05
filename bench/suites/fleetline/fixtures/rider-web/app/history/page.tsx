import { listTrips } from "../../lib/api";

export default async function HistoryPage() {
  const trips = await listTrips();
  return <ul>{trips.map((t) => <li key={t.id}>{t.id}</li>)}</ul>;
}
