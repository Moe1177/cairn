// Service names resolve through the cluster's DNS.
// e.g. curl http://catalogue/catalogue?size=5 from a pod
module.exports = {
  catalogueUrl: util.format("http://catalogue%s", domain),
  basketUrl: "http://basket:8080/basket",
  statusUrl: "http://api.github.com/repos/acme/status",
  devUrl: "http://localhost:8079/",
  selfUrl: "http://storefront/index.html",
};
