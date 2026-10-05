import type { Order } from "@shopverse/types";
import { cartTotal, type CartItem } from "../../lib/cart";

export async function placeOrder(items: CartItem[]): Promise<Order> {
  const body = { items, total: cartTotal(items) };
  const res = await fetch(`${process.env.NEXT_PUBLIC_ORDERS_API}/orders`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return (await res.json()) as Order;
}

export default function CheckoutPage() {
  return <form action="/checkout">Checkout</form>;
}
