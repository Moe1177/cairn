SELECT date_trunc('day', t.created_at) AS day, sum(t.fare_cents) AS gross_cents, sum(p.amount_cents) AS charged_cents
FROM trips t
JOIN payments p ON p.trip_id = t.id
WHERE t.status = 'completed'
GROUP BY 1;
