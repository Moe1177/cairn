# Related repositories (hand-maintained)

GOV.UK One Login identity proving (IPV): IPV Core runs the user's identity journey and calls out to credential issuers (CRIs), each of which checks one kind of evidence and returns a signed verifiable credential (VC). Everything runs on AWS, deployed with SAM/CloudFormation.

- ipv-cri-common-infrastructure: shared CloudFormation for every CRI account: the `core` stack (KMS VC signing and JAR decryption keys, API Gateway API keys, published JWKS), the `txma` stack (audit event SQS queue and its KMS key), plus DNS zone/record templates.
- ipv-cri-common-lambdas: the OAuth Lambdas every CRI shares (Session, Authorization, AccessToken, Java and TypeScript), the session and person-identity DynamoDB tables, and the SSM parameters CRIs read (table names, VC issuer, signing key id, per-client JWT config). Deployed into each CRI account as `common-cri-api`.
- ipv-cri-address-api: Address CRI. Postcode lookup (Ordnance Survey), saves addresses, issues the address VC.
- ipv-cri-kbv-api: Experian knowledge-based verification CRI. Questions/answers against Experian, issues the KBV VC.
- ipv-cri-dl-api: Driving licence CRI. Checks DVLA/DVA, issues the driving-permit VC. Has its own ACM/KMS certificate stack.
- ipv-cri-dl-front: Node/Express front end for the driving licence CRI, deployed on ECS Fargate.
- ipv-cri-check-hmrc-api: Check-HMRC (NINO) CRI, TypeScript Lambdas plus Step Functions.
- ipv-core-back: IPV Core back end (Java Lambdas behind API Gateway): journey state machine, CRI OAuth calls, identity building.
- ipv-core-front: IPV Core front end (Node/Express on ECS) that renders the journey pages.
- ipv-stubs: test stubs owned by IPV Core and the CRI teams: orchestrator stub, IPV Core stub (for CRI teams), credential-issuer stubs, and stubs for CIMIT, EVCS, AIS, TICF, SIS and DCMAW-async.

How they connect:

- Every CRI API imports the txma audit queue (`txma-infrastructure` stack) and the `core-infrastructure` KMS keys and API keys from ipv-cri-common-infrastructure. ipv-cri-common-lambdas uses the same queue and keys.
- Every CRI API plugs the shared Session/Authorization/AccessToken Lambdas from ipv-cri-common-lambdas into its own API Gateway, and reads the shared session and person-identity tables through `/common-cri-api/...` SSM parameters.
- ipv-cri-dl-front talks to ipv-cri-dl-api through dl-api's private API Gateway (stack export `dl-cri-api-v1-PrivateDlApiGatewayId`).
- ipv-core-front talks to ipv-core-back through core-back's private API Gateway (`IPVCorePrivateAPIGatewayID-<env>`).
- ipv-core-back is the OAuth client of the CRIs: it exchanges the auth code at each CRI's token endpoint (the shared AccessToken Lambda) and fetches the VC from the CRI's credential endpoint. The contracts are Pact tests (AddressCriVcProvider, DrivingLicenceVcProvider, ExperianKbvCriVcProvider, NinoCriVcProvider, *TokenProvider).
- In dev and build, ipv-stubs stands in on both sides: the orchestrator stub starts journeys in core-front and calls core-back; the credential-issuer and service stubs replace CRIs and other services for core-back; the IPV Core stub plays core for the CRI teams, calling the CRI APIs and starting the DL front journey.
- IPV Core runs in its own AWS accounts, so its audit queue and DNS zones are not the CRI ones from ipv-cri-common-infrastructure, even where the export names match.
