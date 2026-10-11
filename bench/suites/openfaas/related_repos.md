# Related repositories (hand-maintained)

OpenFaaS: functions as a service on Kubernetes or a single host. The org is split into many small repos; this is the set we keep cloned side by side.

Core platform:

- faas: the API gateway (gateway/), plus the API spec and the built-in UI. Proxies function calls, enqueues async calls, scales from zero.
- faas-provider: Go library every provider builds on: the /system/* REST routes, shared request/response types, basic auth, the invoke proxy.
- faas-netes: the Kubernetes provider, plus all the Helm charts (openfaas, queue-worker, the connector charts).
- faasd: the containerd provider for a single host; ships its own docker-compose.yaml for the core services.
- nats-queue-worker: Community Edition async worker; pulls queued invocations off NATS and calls the functions.
- faas-cli: the CLI (build, push, deploy, templates, store).
- go-sdk / python-sdk: client libraries for the gateway REST API.
- of-watchdog / classic-watchdog: the in-container process that turns HTTP into function calls. Templates copy the binary from these images.
- faas-middleware: shared HTTP middleware (concurrency limiter, auth) used by the watchdogs.
- connector-sdk: library for event connectors (subscribe to a source, invoke matching functions).
- cron-connector, mqtt-connector, nats-connector: connectors built on connector-sdk.
- ingress-operator: FunctionIngress CRD/controller for custom domains on Kubernetes.

Templates and store:

- templates, templates-classic, golang-http-template, python-flask-template, dotnet-templates, ruby-http: function templates pulled by `faas-cli template pull`.
- templates-sdk: shared code used by some templates (Go request/response types, Java model).
- store: the template and function store manifests (templates.json, functions.json).
- store-functions: source for the ready-made store functions.

Other:

- certifier: end-to-end conformance tests run against a live provider.
- config-checker: reads a cluster's OpenFaaS deployment and warns about bad timeouts/scaling settings.
- docs, workshop: documentation and the training workshop.
- openfaas-cloud, ofc-bootstrap, faas-swarm, cloud-functions: archived; kept for reference only.
- mass-deploy, license-check, release-promoter, function-builder-examples, social-functions: small tools and examples.

How they connect:

- Clients (faas-cli, the SDKs, the UI) only talk to the gateway. The gateway forwards /system/* calls to whichever provider is configured (faas-netes on Kubernetes, faasd on a single host).
- Providers get their HTTP API from faas-provider, so a change to the provider API or its shared types usually touches faas-provider, the gateway and both providers, plus the clients.
- Async calls: the gateway puts the request on NATS; the queue-worker picks it up and invokes the function back through the gateway.
- Connectors watch the gateway's function list and invoke functions whose annotations match the event's topic.
- Scaling settings are labels on each function; the gateway and the providers read them at deploy/scale time.
- Gateway and queue-worker versions and env settings are pinned in faasd's compose file and in the Helm chart, and need bumping on release.
- Templates build function images on top of a watchdog image; the store lists which repo each template comes from.
