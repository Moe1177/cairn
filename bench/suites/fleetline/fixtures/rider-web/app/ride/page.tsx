import { Button } from "@fleetline/ui-kit";
import { requestRide } from "../../lib/api";

export default function RidePage() {
  return (
    <form action={requestRide}>
      <input name="pickup" placeholder="Pickup" />
      <input name="dropoff" placeholder="Drop-off" />
      <Button variant="primary" type="submit">Request ride</Button>
    </form>
  );
}
