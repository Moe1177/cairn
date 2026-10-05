const express = require('express');
const axios = require('axios');
const app = express();
const BILLING = process.env.BILLING_SVC_URL;
const audience = process.env.INTERNAL_AUTH_AUDIENCE;

app.get('/health', (req, res) => res.send('ok'));
app.get('/api/rides/:id', async (req, res) => {
  const trip = await axios.get(`${process.env.TRIPS_API_URL}/trips/${req.params.id}`);
  const invoice = await fetch(`${BILLING}/invoices`);
  res.json({ trip: trip.data, invoice: await invoice.json(), audience });
});
app.listen(process.env.PORT);
