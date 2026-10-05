# Related repositories (hand-maintained, last updated 2025)

- rider-web, driver-web, admin-console: the three web apps (Next.js).
- ui-kit: shared components. api-types: shared API types.
- trips-svc: trips backend. pricing-svc: fares and surge. drivers-svc: driver accounts.
- riders-svc: rider profiles. payments-svc: charging and payouts.
- notifications-worker: emails and pushes.
- analytics-etl: reporting.
- infra: docker-compose and terraform.
- geo-svc: maps stuff.
- legacy-dispatch: old dispatch system, don't touch.

Most services own their own tables. The admin console and analytics read the main database.
