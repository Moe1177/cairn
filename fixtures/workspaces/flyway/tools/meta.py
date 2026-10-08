from google.protobuf.internal import containers

METADATA_URL = "http://metadata.google.internal/computeMetadata/v1/"
LOCAL_TLS = "https://host.docker.internal:8443"
NODE = "ip-10-0-0-1.ec2.internal"


def wrap(x):
    return containers.RepeatedScalarFieldContainer(x)
