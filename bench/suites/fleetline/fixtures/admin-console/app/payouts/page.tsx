import { pendingPayouts } from "../../lib/db";

export default async function PayoutsPage() {
  const rows = await pendingPayouts();
  return <p>{rows.length} payouts pending</p>;
}
