import type { DriverApplication } from "@fleetline/api-types";
import { submitApplication } from "../../lib/api";

export default function OnboardingPage() {
  async function submit(form: FormData) {
    "use server";
    const application: DriverApplication = {
      name: String(form.get("name")),
      license_no: String(form.get("license_no")),
    };
    await submitApplication(application);
  }
  return (
    <form action={submit}>
      <input name="name" />
      <input name="license_no" placeholder="Driver's license number" />
      <button type="submit">Apply</button>
    </form>
  );
}
