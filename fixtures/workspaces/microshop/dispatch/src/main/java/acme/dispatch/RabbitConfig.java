package acme.dispatch;

public class RabbitConfig {
    static final String queueName = "dispatch-task";
    @Bean Queue queue() { return new Queue(queueName, false); }
}
