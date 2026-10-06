package acme.ops;

public class QueueAdmin {
    static final String queueName = "dispatch-task";
    @Bean Queue queue() { return new Queue(queueName, false); }
}
