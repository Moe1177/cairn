const { EventBridgeClient, PutEventsCommand } = require("@aws-sdk/client-eventbridge");

const client = new EventBridgeClient({});

exports.handler = async (order) => {
  await client.send(
    new PutEventsCommand({
      Entries: [
        {
          EventBusName: "cloudshop-bus",
          Source: "cloudshop.orders",
          DetailType: "OrderPlaced",
          Detail: JSON.stringify(order),
        },
      ],
    }),
  );
};
