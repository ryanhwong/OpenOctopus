import boto3

from openoctopus.config import Settings


class R2Storage:
    def __init__(self, s3_client, bucket: str, public_base: str):
        self.s3 = s3_client
        self.bucket = bucket
        self.public_base = public_base.rstrip("/")

    def put(self, key: str, data: bytes, mime: str = "image/png") -> str:
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=mime)
        return f"{self.public_base}/{key}"


def make_r2(settings: Settings) -> R2Storage | None:
    if not (settings.r2_bucket and settings.r2_access_key_id and settings.r2_public_base_url):
        return None
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
    )
    return R2Storage(s3, settings.r2_bucket, settings.r2_public_base_url)
