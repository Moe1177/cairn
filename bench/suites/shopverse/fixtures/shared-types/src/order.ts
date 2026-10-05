export interface OrderItem {
  sku: string;
  quantity: number;
}

export interface Order {
  id: string;
  status: "pending" | "paid" | "refunded";
  total: number;
  items: OrderItem[];
}
