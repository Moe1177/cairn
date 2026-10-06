# Related repositories (hand-maintained)

Sock Shop: an online sock store split into small services, each in its own repo and container.

- front-end: Node.js/Express. Serves the shop UI (static HTML/JS) and an API layer that proxies browser requests to the backend services. Sessions can be kept in Redis (session-db) in production.
- catalogue: Go (go-kit). Sock listings, tags and product images, backed by MySQL (catalogue-db).
- carts: Java/Spring Boot. Shopping carts and cart items, backed by MongoDB (carts-db).
- orders: Java/Spring Boot. Places and stores orders in MongoDB (orders-db).
- payment: Go (go-kit). Stateless payment authorisation; declines amounts over a configured limit.
- user: Go (go-kit). Customers, addresses, cards, login and registration, backed by MongoDB (user-db).
- shipping: Java/Spring Boot. Accepts shipment requests and puts them on a RabbitMQ queue.
- queue-master: Java/Spring Boot. Consumes shipment tasks from the RabbitMQ queue (currently just logs them).
- microservices-demo: deployment and ops for the whole shop: docker-compose, Kubernetes manifests, Helm chart, monitoring/logging/alerting configs, load-test deployment, and docs.

How they connect:

- The browser only talks to front-end. Front-end calls catalogue, carts, orders and user over HTTP, addressing each by its service hostname (optionally with a domain suffix).
- At checkout, front-end posts to orders with links to the customer, address, card (user) and cart items (carts). Orders fetches those, asks payment to authorise the total, then asks shipping to ship.
- Shipping publishes the shipment to RabbitMQ; queue-master picks it up from there.
- All services talk plain HTTP/JSON on their service names (catalogue, carts, orders, payment, user, shipping). Several services can send traces to Zipkin when enabled.
- Each service repo has its own Dockerfile and tests (most also have a small local docker-compose); the full-stack deployment config lives only in microservices-demo.
