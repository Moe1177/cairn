const { GeoServiceClient } = require('./gen/geo_grpc_pb');
const { BillingServiceClient } = require('./gen/billing_grpc_pb');
const geo = new GeoServiceClient(process.env.GEO_GRPC_ADDR, credentials);
const billing = new BillingServiceClient(process.env.GEO_GRPC_ADDR, credentials);
module.exports = { geo, billing };
