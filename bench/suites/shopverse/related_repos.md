# Related repositories (hand-maintained)

This folder holds the shopverse services. Keep this list updated when repos change.

- storefront: the customer website (Next.js). Talks to the orders API.
- admin: internal back-office for staff (Next.js).
- orders-svc: the orders backend (Python/FastAPI). Owns the orders database.
- payments-svc: payment processing (Go). Reads orders, keeps its own ledger.
- shared-types: TypeScript types shared by the two Next.js apps.
- notifications-worker: sends emails after payments.

Notes:
- The admin app and payments-svc both read the orders table directly.
- Ask the orders team before changing the orders schema.
