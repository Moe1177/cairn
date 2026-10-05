import { Button } from "@fleetline/ui-kit";
import { driverById } from "../../../lib/db";

export default async function DriverPage({ params }: { params: { id: string } }) {
  const [driver] = await driverById(params.id);
  return (
    <section>
      <h1>{driver.name}</h1>
      <Button variant="danger">Suspend driver</Button>
    </section>
  );
}
