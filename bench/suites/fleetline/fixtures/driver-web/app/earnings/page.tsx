import { Button, Card } from "@fleetline/ui-kit";
import { getEarnings } from "../../lib/api";

export default async function EarningsPage() {
  const weeks = await getEarnings();
  return (
    <Card title="Earnings">
      {weeks.map((w) => <p key={w.week}>{w.week}: {w.total}</p>)}
      <Button variant="secondary">Download statement</Button>
    </Card>
  );
}
