import { sql } from "./sql";

export const listOrders = sql`SELECT id, status, total FROM orders ORDER BY id DESC`;

export function setOrderStatus(id: string, s: string) {
  return sql`UPDATE orders SET status = ${s} WHERE id = ${id}`;
}
