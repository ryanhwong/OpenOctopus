from openoctopus.config import Settings
from openoctopus.storage.r2 import R2Storage, make_r2


class FakeS3:
    def put_object(self, **kw):
        self.kw = kw


def test_put_returns_public_url():
    s3 = FakeS3()
    r2 = R2Storage(s3, "mybucket", "https://cdn.example.com")
    url = r2.put("images/1.png", b"data", mime="image/png")
    assert url == "https://cdn.example.com/images/1.png"
    assert s3.kw["Bucket"] == "mybucket" and s3.kw["ContentType"] == "image/png"


def test_make_r2_none_when_unconfigured():
    assert make_r2(Settings(_env_file=None, r2_bucket="")) is None
