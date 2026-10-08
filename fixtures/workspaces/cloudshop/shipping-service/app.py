import boto3

sqs = boto3.client("sqs")


def handler(event, context):
    queue_url = sqs.get_queue_url(QueueName="payment-requests-prod")["QueueUrl"]
    message = event["Records"][0]["Sns"]["Message"]
    sqs.send_message(QueueUrl=queue_url, MessageBody=message)
