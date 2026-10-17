"""What a repo is built with, in the words its code uses: the datastores, queues, frameworks,
auth, test and deploy tools an agent should search the org with.

A technology counts for a repo when a manifest depends on one of its packages, a repo topic
names it, a file path mentions it (`dynamodb_table.py`), or a file it needs is there
(`cdk.json`). Packages are `ecosystem:name`; a name ending in `*` is a prefix.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

CATEGORIES = (
    "Datastores",
    "Messaging",
    "Serverless and APIs",
    "Web frameworks",
    "Data access",
    "Auth",
    "Observability",
    "Testing",
    "Deploy and CI",
)


@dataclass(frozen=True)
class Tech:
    name: str
    category: str
    packages: tuple[str, ...] = ()  # ecosystem:name, or ecosystem:prefix*
    topics: tuple[str, ...] = ()
    words: tuple[str, ...] = ()  # path words that mean it (lower case)
    files: str = ""  # a regex over file paths


def _t(
    name: str, category: str, *packages: str, topics: str = "", words: str = "", files: str = ""
) -> Tech:
    return Tech(name, category, packages, tuple(topics.split()), tuple(words.split()), files)


_D, _M, _S, _W = "Datastores", "Messaging", "Serverless and APIs", "Web frameworks"
_A, _U, _O, _T, _C = "Data access", "Auth", "Observability", "Testing", "Deploy and CI"

TECHS: tuple[Tech, ...] = (
    _t("DynamoDB", _D, "npm:@aws-sdk/client-dynamodb", "npm:@aws-sdk/lib-dynamodb",
       "npm:dynamoose", "npm:electrodb", "python:pynamodb", "maven:software.amazon.awssdk:dynamodb*",
       "maven:com.amazonaws:aws-java-sdk-dynamodb", "go:github.com/aws/aws-sdk-go-v2/service/dynamodb",
       "go:github.com/guregu/dynamo", topics="dynamodb amazon-dynamodb", words="dynamodb ddb"),
    _t("PostgreSQL", _D, "python:psycopg2", "python:psycopg2-binary", "python:psycopg",
       "python:asyncpg", "npm:pg", "npm:postgres", "npm:pg-promise", "go:github.com/lib/pq",
       "go:github.com/jackc/pgx*", "maven:org.postgresql:postgresql",
       topics="postgresql postgres aurora-postgresql", words="postgres postgresql pgvector"),
    _t("MySQL", _D, "python:pymysql", "python:mysqlclient", "python:mysql-connector-python",
       "npm:mysql", "npm:mysql2", "go:github.com/go-sql-driver/mysql",
       "maven:mysql:mysql-connector-java", "maven:com.mysql:mysql-connector-j",
       topics="mysql aurora-mysql", words="mysql"),
    _t("MongoDB", _D, "python:pymongo", "python:motor", "python:mongoengine", "npm:mongodb",
       "npm:mongoose", "go:go.mongodb.org/mongo-driver*", "maven:org.mongodb:*",
       topics="mongodb", words="mongo mongodb"),
    _t("DocumentDB", _D, topics="documentdb amazon-documentdb", words="documentdb docdb"),
    _t("Redis", _D, "python:redis", "npm:redis", "npm:ioredis", "go:github.com/redis/go-redis*",
       "go:github.com/go-redis/redis*", "maven:redis.clients:jedis", "maven:io.lettuce:lettuce-core",
       topics="redis elasticache", words="redis elasticache valkey"),
    _t("SQLite", _D, "npm:sqlite3", "npm:better-sqlite3", "python:aiosqlite",
       "go:github.com/mattn/go-sqlite3", words="sqlite"),
    _t("OpenSearch/Elasticsearch", _D, "python:opensearch-py", "python:elasticsearch",
       "npm:@opensearch-project/opensearch", "npm:@elastic/elasticsearch",
       "go:github.com/elastic/go-elasticsearch*", topics="opensearch elasticsearch",
       words="opensearch elasticsearch"),
    _t("S3", _D, "npm:@aws-sdk/client-s3", "python:s3fs", "maven:software.amazon.awssdk:s3",
       "go:github.com/aws/aws-sdk-go-v2/service/s3", topics="s3 amazon-s3", words="s3"),
    _t("Neptune", _D, topics="neptune amazon-neptune", words="neptune gremlin"),
    _t("Firestore", _D, "npm:@google-cloud/firestore", "npm:firebase-admin",
       "python:google-cloud-firestore", "python:firebase-admin", topics="firestore firebase"),
    _t("Supabase", _D, "npm:@supabase/supabase-js", "python:supabase", topics="supabase"),
    _t("SQS", _M, "npm:@aws-sdk/client-sqs", "maven:software.amazon.awssdk:sqs",
       "go:github.com/aws/aws-sdk-go-v2/service/sqs", topics="sqs amazon-sqs", words="sqs"),
    _t("SNS", _M, "npm:@aws-sdk/client-sns", "maven:software.amazon.awssdk:sns",
       "go:github.com/aws/aws-sdk-go-v2/service/sns", topics="sns amazon-sns", words="sns"),
    _t("EventBridge", _M, "npm:@aws-sdk/client-eventbridge",
       "maven:software.amazon.awssdk:eventbridge", topics="eventbridge amazon-eventbridge",
       words="eventbridge"),
    _t("Kinesis", _M, "npm:@aws-sdk/client-kinesis", "maven:software.amazon.kinesis:*",
       topics="kinesis amazon-kinesis kinesis-data-streams", words="kinesis firehose"),
    _t("Kafka", _M, "python:kafka-python", "python:confluent-kafka", "python:aiokafka",
       "npm:kafkajs", "go:github.com/segmentio/kafka-go", "go:github.com/confluentinc/*",
       "go:github.com/IBM/sarama", "maven:org.apache.kafka:*", "maven:org.springframework.kafka:*",
       topics="kafka apache-kafka msk amazon-msk", words="kafka msk"),
    _t("RabbitMQ", _M, "python:pika", "python:aio-pika", "npm:amqplib",
       "go:github.com/rabbitmq/amqp091-go", "maven:org.springframework.boot:spring-boot-starter-amqp",
       topics="rabbitmq amazon-mq", words="rabbitmq amqp"),
    _t("Celery", _M, "python:celery"),
    _t("AWS Lambda", _S, "python:aws-lambda-powertools", "python:mangum", "npm:@types/aws-lambda",
       "npm:@aws-lambda-powertools/*", "npm:@middy/core", "go:github.com/aws/aws-lambda-go",
       "maven:com.amazonaws:aws-lambda-java-*", topics="lambda aws-lambda serverless",
       words="lambda"),
    _t("Lambda Powertools", _S, "python:aws-lambda-powertools", "npm:@aws-lambda-powertools/*",
       "maven:software.amazon.lambda:powertools-*", topics="powertools aws-lambda-powertools"),
    _t("Step Functions", _S, "npm:@aws-sdk/client-sfn", "maven:software.amazon.awssdk:sfn",
       topics="step-functions aws-step-functions stepfunctions",
       words="stepfunctions statemachine sfn"),
    _t("API Gateway", _S, "npm:@aws-sdk/client-api-gateway", topics="api-gateway apigateway amazon-api-gateway",
       words="apigateway apigw"),
    _t("AppSync/GraphQL", _S, "npm:graphql", "npm:@apollo/server", "npm:apollo-server*",
       "python:strawberry-graphql", "python:graphene", "python:ariadne", "maven:com.graphql-java:*",
       topics="graphql appsync aws-appsync", words="graphql appsync resolvers"),
    _t("gRPC", _S, "python:grpcio", "npm:@grpc/grpc-js", "go:google.golang.org/grpc",
       "maven:io.grpc:*", topics="grpc", words="grpc proto protobuf"),
    _t("Bedrock", _S, "npm:@aws-sdk/client-bedrock-runtime", "npm:@aws-sdk/client-bedrock-agent-runtime",
       "python:langchain-aws", "maven:software.amazon.awssdk:bedrockruntime",
       topics="bedrock amazon-bedrock", words="bedrock"),
    _t("FastAPI", _W, "python:fastapi"),
    _t("Flask", _W, "python:flask"),
    _t("Django", _W, "python:django"),
    _t("Streamlit", _W, "python:streamlit"),
    _t("Express", _W, "npm:express"),
    _t("Fastify", _W, "npm:fastify"),
    _t("NestJS", _W, "npm:@nestjs/core"),
    _t("Hono", _W, "npm:hono"),
    _t("Next.js", _W, "npm:next"),
    _t("React", _W, "npm:react"),
    _t("Vue", _W, "npm:vue"),
    _t("Angular", _W, "npm:@angular/core"),
    _t("Spring Boot", _W, "maven:org.springframework.boot:*"),
    _t("Quarkus", _W, "maven:io.quarkus:*"),
    _t("Gin", _W, "go:github.com/gin-gonic/gin"),
    _t("Echo", _W, "go:github.com/labstack/echo*"),
    _t("Fiber", _W, "go:github.com/gofiber/fiber*"),
    _t("Rails", _W, "ruby:rails"),
    _t("SQLAlchemy", _A, "python:sqlalchemy"),
    _t("Prisma", _A, "npm:prisma", "npm:@prisma/client"),
    _t("Drizzle", _A, "npm:drizzle-orm"),
    _t("TypeORM", _A, "npm:typeorm"),
    _t("Sequelize", _A, "npm:sequelize"),
    _t("Hibernate/JPA", _A, "maven:org.hibernate*", "maven:org.springframework.boot:spring-boot-starter-data-jpa"),
    _t("GORM", _A, "go:gorm.io/gorm"),
    _t("Pydantic", _A, "python:pydantic"),
    _t("Cognito", _U, "npm:@aws-sdk/client-cognito-identity-provider", "npm:amazon-cognito-identity-js",
       "npm:aws-jwt-verify", "python:pycognito", topics="cognito amazon-cognito", words="cognito"),
    _t("Auth0", _U, "npm:auth0", "npm:@auth0/*", "python:auth0-python", topics="auth0"),
    _t("Okta", _U, "npm:@okta/*", "python:okta", topics="okta"),
    _t("NextAuth", _U, "npm:next-auth", "npm:@auth/*"),
    _t("Passport", _U, "npm:passport"),
    _t("JWT", _U, "npm:jsonwebtoken", "npm:jose", "python:pyjwt", "python:python-jose",
       "go:github.com/golang-jwt/jwt*", "maven:io.jsonwebtoken:*", words="jwt"),
    _t("Spring Security", _U, "maven:org.springframework.boot:spring-boot-starter-security",
       "maven:org.springframework.security:*"),
    _t("OpenTelemetry", _O, "npm:@opentelemetry/*", "python:opentelemetry-*",
       "go:go.opentelemetry.io/*", "maven:io.opentelemetry:*", topics="opentelemetry",
       words="otel opentelemetry"),
    _t("X-Ray", _O, "python:aws-xray-sdk", "npm:aws-xray-sdk*", topics="xray aws-xray", words="xray"),
    _t("CloudWatch", _O, "npm:@aws-sdk/client-cloudwatch*", topics="cloudwatch amazon-cloudwatch",
       words="cloudwatch"),
    _t("Prometheus", _O, "python:prometheus-client", "npm:prom-client",
       "go:github.com/prometheus/client_golang", topics="prometheus", words="prometheus"),
    _t("Datadog", _O, "python:ddtrace", "python:datadog", "npm:dd-trace", topics="datadog"),
    _t("Sentry", _O, "python:sentry-sdk", "npm:@sentry/*", topics="sentry"),
    _t("pytest", _T, "python:pytest", files=r"(?:^|/)conftest\.py$"),
    _t("moto", _T, "python:moto"),
    _t("Jest", _T, "npm:jest", files=r"(?:^|/)jest\.config\.[cm]?[jt]s$"),
    _t("Vitest", _T, "npm:vitest"),
    _t("Mocha", _T, "npm:mocha"),
    _t("Playwright", _T, "npm:@playwright/test", "python:playwright"),
    _t("Cypress", _T, "npm:cypress"),
    _t("JUnit", _T, "maven:org.junit*", "maven:junit:junit"),
    _t("testify", _T, "go:github.com/stretchr/testify"),
    _t("AWS CDK", _C, "npm:aws-cdk-lib", "npm:aws-cdk", "python:aws-cdk-lib",
       "maven:software.amazon.awscdk:*", "go:github.com/aws/aws-cdk-go/*", files=r"(?:^|/)cdk\.json$"),
    _t("AWS SAM", _C, files=r"(?:^|/)(?:samconfig\.toml|template\.ya?ml)$"),
    _t("CloudFormation", _C, topics="cloudformation aws-cloudformation",
       files=r"(?:^|/)(?:cloudformation|cfn)/|\.(?:template|cfn)\.(?:ya?ml|json)$"),
    _t("Serverless Framework", _C, "npm:serverless", files=r"(?:^|/)serverless\.(?:ya?ml|ts|js)$"),
    _t("Terraform", _C, topics="terraform", files=r"\.tf$"),
    _t("Pulumi", _C, files=r"(?:^|/)Pulumi\.ya?ml$"),
    _t("Docker", _C, files=r"(?:^|/)Dockerfile[^/]*$"),
    _t("Docker Compose", _C, files=r"(?:^|/)(?:docker-)?compose\.ya?ml$"),
    _t("Helm", _C, files=r"(?:^|/)Chart\.yaml$"),
    _t("Kubernetes", _C, topics="kubernetes eks amazon-eks k8s", words="k8s kubernetes eks"),
    _t("GitHub Actions", _C, files=r"^\.github/workflows/[^/]+\.ya?ml$"),
    _t("GitLab CI", _C, files=r"^\.gitlab-ci\.ya?ml$"),
    _t("Jenkins", _C, files=r"(?:^|/)Jenkinsfile$"),
    _t("CodeBuild/CodePipeline", _C, files=r"(?:^|/)buildspec[^/]*\.ya?ml$"),
    _t("Amplify", _C, "npm:aws-amplify", "npm:@aws-amplify/*", files=r"(?:^|/)amplify\.ya?ml$"),
    _t("Vercel", _C, files=r"^vercel\.json$"),
)  # fmt: skip

_WORD = re.compile(r"[a-z0-9]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_EXACT: dict[str, set[str]] = {}  # ecosystem:name -> techs
_PREFIXES: list[tuple[str, str]] = []  # (ecosystem:prefix, tech)
_TOPICS: dict[str, set[str]] = {}
_WORDS: dict[str, set[str]] = {}
for _tech in TECHS:
    for _spec in _tech.packages:
        if _spec.endswith("*"):
            _PREFIXES.append((_spec[:-1].lower(), _tech.name))
        else:
            _EXACT.setdefault(_spec.lower(), set()).add(_tech.name)
    for _topic in _tech.topics:
        _TOPICS.setdefault(_topic, set()).add(_tech.name)
    for _word in _tech.words:
        _WORDS.setdefault(_word, set()).add(_tech.name)
_FILES = [(re.compile(t.files), t.name) for t in TECHS if t.files]
CATEGORY = {t.name: t.category for t in TECHS}


def path_words(path: str) -> set[str]:
    """The words of a file path, and each pair of neighbours joined: `src/DynamoDBTable.ts`
    -> src, dynamo, db, table, ts, dynamodb, dbtable, dynamodbtable, ..."""
    parts = _WORD.findall(_CAMEL.sub(" ", path).lower())
    pairs = {a + b for a, b in zip(parts, parts[1:], strict=False)}
    return set(parts) | pairs | set(_WORD.findall(path.lower()))


def package_techs(packages: Iterable[str]) -> set[str]:
    """Techs for `ecosystem:name` packages."""
    found: set[str] = set()
    for package in packages:
        key = package.lower()
        found |= _EXACT.get(key, set())
        found |= {tech for prefix, tech in _PREFIXES if key.startswith(prefix)}
    return found


def repo_techs(packages: Iterable[str], topics: Iterable[str], paths: Iterable[str]) -> set[str]:
    """Every tech a repo shows: by its packages, its topics, and its file paths."""
    found = package_techs(packages)
    for topic in topics:
        found |= _TOPICS.get(topic.lower(), set())
    words: set[str] = set()
    for path in paths:
        words |= path_words(path)
        found |= {tech for pattern, tech in _FILES if pattern.search(path)}
    for word in words:
        found |= _WORDS.get(word, set())
    return found
