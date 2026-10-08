import * as cdk from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as events from "aws-cdk-lib/aws-events";
import * as sqs from "aws-cdk-lib/aws-sqs";

export class NotificationsStack extends cdk.Stack {
  constructor(scope: cdk.App, id: string, props?: cdk.StackProps) {
    super(scope, id, props);
    const bus = events.EventBus.fromEventBusName(this, "Bus", "cloudshop-bus");
    new events.Rule(this, "OrderPlaced", {
      eventBus: bus,
      eventPattern: { source: ["cloudshop.orders"], detailType: ["OrderPlaced"] },
    });
    // From the docs: arn:aws:sqs:us-east-1:123456789012:payment-requests
    dynamodb.Table.fromTableName(this, "Orders", "orders-prod");
    new sqs.Queue(this, "Emails", { queueName: "notification-emails" });
    // AWS's own events are not a sibling service.
    new events.Rule(this, "Ec2", { eventPattern: { source: ["aws.ec2"] } });
  }
}
