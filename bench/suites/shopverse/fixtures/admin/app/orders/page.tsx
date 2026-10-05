import { listOrders } from "../../lib/db";

export default async function OrdersPage() {
  const orders = await listOrders;
  return <pre>{JSON.stringify(orders)}</pre>;
}
