SELECT d.id, d.license_no, count(*) AS trips
FROM drivers d
GROUP BY d.id, d.license_no;
