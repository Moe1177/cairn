"""Phase 4 Task 3: Spring AMQP (RabbitMQ) publishers and consumers link through a queue."""

from pathlib import Path

from cairn.model.graph import EdgeType
from cairn.scan import scan_workspace
from tests.helpers import make_repo

PUBLISHER = """@RestController
public class ShippingController {
    public void ship(Shipment shipment) {
        rabbitTemplate.convertAndSend("shipping-task", shipment);
    }
}
"""
SHARED_CONFIG = """@Configuration
public class RabbitMqConfiguration {
    final static String queueName = "shipping-task";
    @Bean Queue queue() { return new Queue(queueName, false); }
}
"""
CONSUMER = """@Configuration
public class ShippingConsumerConfiguration extends RabbitMqConfiguration {
    protected final String queueName = "shipping-task";

    @Bean
    public SimpleMessageListenerContainer listenerContainer() {
        SimpleMessageListenerContainer container = new SimpleMessageListenerContainer();
        container.setQueueNames(this.queueName);
        return container;
    }
}
"""
ANNOTATED = """public class Invoices {
    @RabbitListener(queues = "invoice-created")
    public void onInvoice(Invoice invoice) {}
}
"""
SENDER = """class Billing { void done() { template.convertAndSend("invoice-created", invoice); } }"""


def _pubsub(ws: Path) -> set[tuple[str, str]]:
    edges = scan_workspace(ws).workspace.edges
    return {(e.source, e.target) for e in edges if e.type is EdgeType.PUBSUB}


def test_convert_and_send_links_to_a_listener_container(tmp_path: Path) -> None:
    make_repo(
        tmp_path,
        "shipping",
        {"src/ShippingController.java": PUBLISHER, "src/RabbitMqConfiguration.java": SHARED_CONFIG},
    )
    make_repo(
        tmp_path,
        "queue-master",
        {"src/RabbitMqConfiguration.java": SHARED_CONFIG, "src/Consumer.java": CONSUMER},
    )
    assert _pubsub(tmp_path) == {("shipping", "queue-master")}


def test_rabbit_listener_annotations_subscribe(tmp_path: Path) -> None:
    make_repo(tmp_path, "billing", {"src/Billing.java": SENDER})
    make_repo(tmp_path, "mailer", {"src/Invoices.java": ANNOTATED})
    assert _pubsub(tmp_path) == {("billing", "mailer")}


def test_declaring_a_queue_is_not_consuming_it(tmp_path: Path) -> None:
    make_repo(tmp_path, "shipping", {"src/ShippingController.java": PUBLISHER})
    make_repo(tmp_path, "ops", {"src/RabbitMqConfiguration.java": SHARED_CONFIG})
    assert _pubsub(tmp_path) == set()
