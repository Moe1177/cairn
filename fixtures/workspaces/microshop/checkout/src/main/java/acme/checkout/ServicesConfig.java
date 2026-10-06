package acme.checkout;

public class ServicesConfig {
    public URI paymentsUri() {
        return new ServiceUri(new Hostname("payments"), domain, "/authorise").toUri();
    }
    public URI dispatchUri() {
        return new ServiceUri(new Hostname("dispatch"), domain, "/dispatch").toUri();
    }
    private String host = "127.0.0.1";
}
