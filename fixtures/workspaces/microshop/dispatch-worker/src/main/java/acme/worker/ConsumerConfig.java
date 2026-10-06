package acme.worker;

public class ConsumerConfig {
    protected final String queueName = "dispatch-task";
    @Bean
    public SimpleMessageListenerContainer listenerContainer() {
        SimpleMessageListenerContainer container = new SimpleMessageListenerContainer();
        container.setQueueNames(this.queueName);
        return container;
    }
}
