"""Spec §25: AWS resources created in one repo and used from another."""

import time
from pathlib import Path

import pytest

from cairn.bench.workspace import materialize
from cairn.detectors.aws import scan_file
from cairn.detectors.aws_names import clean, env_references, from_arn, line_references
from cairn.match.matcher import RepoFacts
from cairn.match.services import resource_edges
from cairn.model.graph import Confidence, Contracts, EdgeType, Fact, FactKind
from cairn.render.card import render_card
from cairn.render.index import render_index
from cairn.scan import scan_workspace

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "workspaces" / "cloudshop"


def _scan(name: str, text: str) -> set[tuple[str, str]]:
    return {(f.side, f.value) for f in scan_file(name, text, text.splitlines())}


# --- names ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["orders-${sls:stage}", "orders-prod", "${var.env}-orders", "prod-orders", "Orders-Dev"],
)
def test_templates_and_literals_reduce_to_one_name(raw: str) -> None:
    assert clean(raw, "sqs") == "orders"


def test_ssm_paths_lose_stage_segments_in_any_placeholder_style() -> None:
    names = {
        clean("/shop/${Environment}/orders/table/name", "ssm"),
        clean("/shop/{Environment}/orders/table/name", "ssm"),
        clean("/shop/prod/orders/table/name", "ssm"),
        clean("shop/orders/table/name", "ssm"),
    }
    assert names == {"/shop/orders/table/name"}


@pytest.mark.parametrize("raw", ["*", "orders-*", "queue", "${sls:stage}", "a b", "x", "true"])
def test_wildcards_generic_and_empty_names_are_no_name(raw: str) -> None:
    assert clean(raw, "sqs") is None


@pytest.mark.parametrize(
    ("service", "rest", "expected"),
    [
        ("sqs", "us-east-1:123456789012:orders-prod", "sqs:orders"),
        ("sns", "${AWS::Region}:${AWS::AccountId}:order-placed", "sns:order-placed"),
        ("sns", "eu-west-1:123456789012:order-placed:6f1c-sub", "sns:order-placed"),
        ("dynamodb", "us-east-1:123456789012:table/orders/stream/2024", "dynamodb:orders"),
        ("dynamodb", "us-east-1:123456789012:table/*", None),
        ("s3", "::cloudshop-receipts/*", "s3:cloudshop-receipts"),
        ("events", "::event-bus/cloudshop-bus", "events:cloudshop-bus"),
        ("events", "::rule/nightly", None),
        ("ssm", "::parameter/shop/prod/api-url", "ssm:/shop/api-url"),
        ("kinesis", "::stream/clicks", "kinesis:clicks"),
        ("sqs", "*:*:*", None),
    ],
)
def test_arns_name_their_resource(service: str, rest: str, expected: str | None) -> None:
    assert from_arn(service, rest) == expected


def test_lines_point_at_resources_by_lookup_and_url() -> None:
    line = (
        "A: ${ssm:/shop/${sls:stage}/api-url} B: {{resolve:ssm:/shop/db-host:3}} "
        "C: ${cf:orders-service-dev.TopicArn} "
        "D: https://sqs.us-east-1.amazonaws.com/123456789012/payments-prod"
    )
    assert set(line_references(line)) == {
        "ssm:/shop/api-url",
        "ssm:/shop/db-host",
        "stack:orders-service",
        "sqs:payments",
    }


def test_env_vars_name_resources_only_with_literal_values() -> None:
    assert list(env_references('  ORDERS_TABLE: "orders-prod"', bare=False)) == ["dynamodb:orders"]
    assert list(env_references("  - PAYMENTS_QUEUE=payments", bare=True)) == ["sqs:payments"]
    assert list(env_references("  ORDERS_TABLE: orders-prod", bare=False)) == []
    assert list(env_references("  TABLE_NAME: props.tableName,", bare=True)) == []
    assert list(env_references("  TABLE_NAME: !Ref OrdersTable", bare=True)) == []


# --- Terraform -----------------------------------------------------------------------------

TERRAFORM = """terraform {
  backend "s3" {
    bucket = "shared-terraform-state"
  }
}

resource "aws_sqs_queue" "q" {
  name = "payments-${var.env}"
  tags = { team = "payments" }
}

data "aws_ssm_parameter" "url" { name = "/shop/${var.env}/orders/url" }

resource "aws_dynamodb_table" "t" {
  name = local.table_name
}

module "topic" {
  name   = "refunds"
  source = "terraform-aws-modules/sns/aws"
}

module "local" {
  source = "./modules/queue"
  name   = "ignored"
}
"""


def test_terraform_resources_create_and_data_sources_use() -> None:
    assert _scan("main.tf", TERRAFORM) == {
        ("exposes", "sqs:payments"),
        ("consumes", "ssm:/shop/orders/url"),
        ("exposes", "sns:refunds"),
    }


# --- CloudFormation / SAM / serverless -----------------------------------------------------

SAM = """Transform: AWS::Serverless-2016-10-31
Parameters:
  BusName:
    Type: AWS::SSM::Parameter::Value<String>
    Default: /shop/platform/bus-name
Resources:
  Queue:
    Type: AWS::SQS::Queue
    Properties:
      QueueName: !Join ["-", [shipments, !Ref Stage]]
  Fn:
    Type: AWS::Serverless::Function
    Properties:
      Policies:
        - SQSSendMessagePolicy:
            QueueName: !GetAtt Queue.QueueName
        - DynamoDBCrudPolicy:
            TableName: !Sub "orders-${Stage}"
      Events:
        Delivered:
          Type: EventBridgeRule
          Properties:
            EventBusName: shop-bus
            Pattern:
              source: [shop.delivery, aws.s3]
              detail-type: [{prefix: Delivery}]
Outputs:
  QueueArn:
    Value: !GetAtt Queue.Arn
    Export:
      Name: !Sub "${AWS::StackName}-QueueArn"
"""


def test_sam_templates_create_what_they_name_and_use_what_policies_name() -> None:
    assert _scan("template.yaml", SAM) == {
        ("exposes", "sqs:shipments"),
        ("exposes", "export:queuearn"),
        ("consumes", "ssm:/shop/platform/bus-name"),
        ("consumes", "dynamodb:orders"),
        ("consumes", "events:shop-bus"),
        ("consumes", "eventbridge:shop.delivery"),
    }


SERVERLESS = """service: billing
custom:
  queue: invoices-${sls:stage}
provider:
  name: aws
  environment:
    INVOICE_QUEUE: ${self:custom.queue}
functions:
  notify:
    handler: h.notify
    events:
      - sns: invoice-sent
      - sns:
          arn: arn:aws:sns:us-east-1:123456789012:order-placed
"""


def test_serverless_fills_in_self_references_and_creates_named_sns_topics() -> None:
    assert _scan("serverless.yml", SERVERLESS) == {
        ("exposes", "stack:billing"),
        ("exposes", "sns:invoice-sent"),
        ("consumes", "sqs:invoices"),
        ("consumes", "sns:order-placed"),
    }


def test_templates_with_unknown_tags_or_broken_yaml_do_not_fail() -> None:
    assert _scan("template.yaml", "Resources: !Bogus [\n") == set()
    assert _scan("template.json", '{"Resources": ') == set()


# --- code ----------------------------------------------------------------------------------

CDK = """import * as sqs from "aws-cdk-lib/aws-sqs";
import * as ssm from "aws-cdk-lib/aws-ssm";
new sqs.Queue(this, "Q", {
  queueName: "emails",
});
const shared = sqs.Queue.fromQueueAttributes(this, "Shared", {
  queueName: "payments",
  queueArn: arn,
});
const url = ssm.StringParameter.valueForStringParameter(this, "/shop/orders/url");
new ssm.StringParameter(this, "P", { parameterName: "/shop/emails/url", stringValue: x });
const table = cdk.Fn.importValue("orders-service-prod-TableName");
"""


def test_cdk_constructs_create_and_lookups_use() -> None:
    assert _scan("stack.ts", CDK) == {
        ("exposes", "sqs:emails"),
        ("consumes", "sqs:payments"),
        ("consumes", "ssm:/shop/orders/url"),
        ("exposes", "ssm:/shop/emails/url"),
        ("consumes", "export:orders-service-tablename"),
    }


SDK = """import boto3
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("orders-prod")
ssm.put_parameter(Name="/shop/payments/url", Value=url)
url = ssm.get_parameter(Name="/shop/orders/url")
sqs.create_queue(QueueName="refunds")
events.put_events(Entries=[{"Source": "shop.payments", "DetailType": "Paid"}])
"""


def test_sdk_calls_use_what_they_name_and_publish_their_event_source() -> None:
    assert _scan("app.py", SDK) == {
        ("consumes", "dynamodb:orders"),
        ("exposes", "ssm:/shop/payments/url"),
        ("consumes", "ssm:/shop/orders/url"),
        ("exposes", "sqs:refunds"),
        ("exposes", "eventbridge:shop.payments"),
    }


def test_a_source_key_without_put_events_publishes_nothing() -> None:
    assert _scan("feed.ts", 'const item = { Source: "rss.feed" };\n') == set()


def test_constant_table_names_in_non_aws_code_are_not_dynamodb() -> None:
    assert _scan("reports.py", 'import psycopg\nTABLE_NAME = "orders"\n') == set()


def test_comments_and_docs_examples_name_nothing() -> None:
    text = "# arn:aws:sqs:us-east-1:123456789012:payments\n// TableName: 'orders'\n"
    assert _scan("app.ts", text) == set()


def test_metadata_maps_of_ssm_paths_are_read_but_filesystem_paths_are_not() -> None:
    text = (
        "parameters:\n  OrdersTableName: /shop/{Environment}/orders/table/name\n"
        "  mountPath: /var/lib/data/x\n  Script: /opt/app/run/x\n"
    )
    assert _scan("metadata.yaml", text) == {("consumes", "ssm:/shop/orders/table/name")}


def test_hostile_lines_scan_in_linear_time() -> None:
    hostile = "\n".join(
        [
            "arn:aws:sqs:" + "${a}" * 20_000,
            "QUEUE_NAME: " + "a-" * 20_000,
            "x: /" + "a/" * 20_000,
            'resource "aws_sqs_queue" "q" {' + "{" * 20_000,
            "source: [" + '"a",' * 20_000,
        ]
    )
    for name in ("template.yaml", "main.tf", "app.ts"):
        start = time.perf_counter()
        scan_file(name, hostile, hostile.splitlines())
        assert time.perf_counter() - start < 2.0, name


# --- matching ------------------------------------------------------------------------------


def _repo(repo_id: str, exposes: tuple[str, ...] = (), consumes: tuple[str, ...] = ()) -> RepoFacts:
    def facts(values: tuple[str, ...]) -> tuple[Fact, ...]:
        return tuple(Fact(kind=FactKind.CLOUD_RESOURCE, value=v) for v in values)

    return RepoFacts(
        id=repo_id,
        path=repo_id,
        contracts=Contracts(exposes=facts(exposes), consumes=facts(consumes)),
    )


def test_a_resource_two_repos_create_links_ambiguously_and_self_use_never_links() -> None:
    edges = resource_edges(
        [
            _repo("a", exposes=("sqs:orders",)),
            _repo("b", exposes=("sqs:orders",), consumes=("sqs:orders",)),
            _repo("c", consumes=("sqs:orders",)),
        ]
    )
    assert {(e.source, e.target, e.confidence) for e in edges} == {
        ("c", "a", Confidence.AMBIGUOUS),
        ("c", "b", Confidence.AMBIGUOUS),
    }


def test_full_export_names_are_extracted_and_stack_relative_ones_inferred() -> None:
    edges = resource_edges(
        [
            _repo("a", exposes=("export:orders-tablename", "export:queuearn")),
            _repo("b", consumes=("export:orders-tablename",)),
            _repo("c", consumes=("export:queuearn",)),
        ]
    )
    tiers = {(e.source, e.confidence) for e in edges}
    assert tiers == {("b", Confidence.EXTRACTED), ("c", Confidence.INFERRED)}


# --- end to end ----------------------------------------------------------------------------


def test_cloudshop_cards_and_index_describe_aws_links(tmp_path: Path) -> None:
    ws = materialize(FIXTURE, tmp_path / "cloudshop").resolve()
    workspace = scan_workspace(ws).workspace
    shipping = workspace.repo("shipping-service")
    orders = workspace.repo("orders-service")
    assert shipping is not None and orders is not None
    card = render_card(shipping, workspace)
    assert "uses DynamoDB table orders, CloudFormation export" in card
    assert "uses SQS queue payment-requests" in card
    assert "publishes EventBridge events cloudshop.orders" in render_card(orders, workspace)
    index = render_index(workspace, {})
    assert "used by notifications-service, shipping-service" in index
    assert not workspace.edges_for("legacy-reports")
    assert "serverless" in orders.stack
    assert any(e.type is EdgeType.USES_RESOURCE for e in workspace.edges)


# --- review regressions: bounded work on hostile templates, fewer look-alikes -----------------


def _timed(name: str, text: str, limit: float = 3.0) -> set[tuple[str, str]]:
    start = time.perf_counter()
    found = _scan(name, text)
    assert time.perf_counter() - start < limit, name
    return found


def test_a_self_referencing_anchor_is_walked_once() -> None:
    refs = ", ".join(["*L"] * 5000)
    text = f"Resources:\n  Q: {{Type: AWS::SQS::Queue}}\nL: &L [{refs}]\n"
    _timed("template.yaml", text)


def test_nested_and_recursive_joins_are_no_name() -> None:
    parts = ", ".join(["*a0"] * 50)
    text = 'a0: &a0 "x"\n'
    for level in range(1, 5):
        text += (
            f'a{level}: &a{level} {{"Fn::Join": ["-", [{parts.replace("a0", f"a{level - 1}")}]]}}\n'
        )
    text += "Resources:\n  Q:\n    Type: AWS::SQS::Queue\n    Properties:\n      QueueName: *a4\n"
    assert _timed("template.yaml", text) == set()
    looped = (
        "Resources:\n  Q:\n    Type: AWS::SQS::Queue\n    Properties:\n"
        '      QueueName: &x {"Fn::Join": ["-", [*x]]}\n  T:\n    Type: AWS::SNS::Topic\n'
        "    Properties:\n      TopicName: alerts-topic\n"
    )
    assert _timed("template.yaml", looped) == {("exposes", "sns:alerts-topic")}


def test_serverless_self_references_cannot_multiply_a_line() -> None:
    refs = lambda name: "${self:custom." + name + "}"  # noqa: E731
    text = (
        "service: s\nprovider: {name: aws}\ncustom:\n  c: " + "x" * 1000 + "\n"
        "  b: "
        + refs("c") * 40
        + "\n  a: "
        + refs("b") * 40
        + "\n"
        + "".join(f"  k{i}: {refs('a') * 40}\n" for i in range(50))
    )
    _timed("serverless.yml", text)


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("app.py", "import boto3\nget_parameter(" + " " * 80_000 + "x\n"),
        ("app.ts", "import '@aws-sdk/x'\n" + ("A_TABLE = 'x'" + " " * 1980 + "z\n") * 400),
        ("main.tf", 'resource "aws_sqs_queue" "q" {\n  name = "' + "a" * 100_000 + '"\n}\n'),
        (
            "template.yaml",
            "Resources:\n"
            + "".join(
                f"  F{i}:\n    Type: X\n    Properties: {{TableName: t-{i}-table}}\n"
                for i in range(5000)
            ),
        ),
    ],
    ids=["ssm-get-spaces", "env-quoted-spaces", "tf-long-name", "many-table-names"],
)
def test_long_lines_and_many_findings_scan_quickly(name: str, text: str) -> None:
    _timed(name, text)


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("models.go", 'import "gorm.io/gorm"\nvar q = db.Table("orders")\n'),
        ("store.go", 'import "cloud.google.com/go/storage"\nb := client.Bucket("media-uploads")\n'),
        ("Consts.cs", 'public const string TableName = "orders";\n'),
        ("Topics.java", 'static final String TopicName = "orders";\n'),
        (
            "docker-compose.yml",
            "aws: x\nservices:\n  a:\n    environment:\n      UPSTREAM: payments-api\n"
            "      STABLE: release-train\n      KAFKA_TOPIC: orders-events\n",
        ),
        ("worker.yml", "# draws from the queue\nORDERS_QUEUE: orders-jobs\n"),
        ("site.yml", "redirects:\n  oldpage: /docs/guide/install\n"),
    ],
    ids=["gorm", "gcs", "csharp-const", "java-const", "compose-envs", "draws-word", "redirects"],
)
def test_look_alikes_from_other_stacks_name_no_aws_resource(name: str, text: str) -> None:
    assert _scan(name, text) == set()


def test_cdk_environment_props_and_split_create_calls_get_the_right_side() -> None:
    cdk = (
        'import * as lambda from "aws-cdk-lib/aws-lambda";\n'
        'new lambda.Function(this, "F", {\n  environment: {\n    tableName: "orders",\n  },\n});\n'
    )
    assert _scan("stack.ts", cdk) == {("consumes", "dynamodb:orders")}
    sdk = 'import boto3\nclient.create_table(\n    TableName="invoices",\n)\n'
    assert _scan("setup.py", sdk) == {("exposes", "dynamodb:invoices")}


def test_other_services_tables_are_not_dynamodb() -> None:
    text = (
        "Resources:\n  T:\n    Type: AWS::Timestream::Table\n    Properties:\n"
        "      TableName: metrics-table\n"
    )
    assert _scan("template.yaml", text) == set()


def test_template_evidence_points_at_the_line_that_names_the_resource() -> None:
    text = (
        "Description: orders service\nResources:\n  Q:\n    Type: AWS::SQS::Queue\n"
        "    Properties:\n      QueueName: orders\n"
    )
    found = scan_file("template.yaml", text, text.splitlines())
    assert [(f.value, f.line_no) for f in found if f.side == "exposes"] == [("sqs:orders", 6)]
