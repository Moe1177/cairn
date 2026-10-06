package acme.dispatch;

public class DispatchController {
    public void book(Shipment shipment) {
        rabbitTemplate.convertAndSend("dispatch-task", shipment);
    }
}
