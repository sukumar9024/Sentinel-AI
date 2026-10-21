"""SigV4 is activated only for explicitly configured AWS OpenSearch deployments."""

import httpx


class OpenSearchAuth(httpx.Auth):
    requires_request_body = True

    def __init__(self, region):
        self.region = region

    def auth_flow(self, request):
        import boto3
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest

        credentials = boto3.Session().get_credentials()
        if credentials is None:
            raise RuntimeError("No task-role credentials available")
        signed = AWSRequest(
            method=request.method, url=str(request.url), data=request.content, headers=dict(request.headers)
        )
        SigV4Auth(credentials.get_frozen_credentials(), "es", self.region).add_auth(signed)
        request.headers.update(dict(signed.headers))
        yield request
