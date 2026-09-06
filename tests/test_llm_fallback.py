from openoctopus.llm_fallback import FallbackChatClient


class _Boom:
    async def create(self, **kw):
        raise RuntimeError("primary down")


class _OK:
    def __init__(self, payload):
        self.payload = payload
        self.seen = []
        self.closed = False

    async def create(self, **kw):
        self.seen.append(kw)
        return self.payload

    async def aclose(self):
        self.closed = True


class _Client:
    def __init__(self, completions):
        self.chat = type("Chat", (), {"completions": completions})()
        self._impl = completions

    async def aclose(self):
        await self._impl.aclose()


def _wrap(primary, fallback, pm="p-model", fm="f-model"):
    return FallbackChatClient(_Client(primary), pm, _Client(fallback), fm)


async def test_primary_used_when_healthy():
    p, f = _OK("P"), _OK("F")
    out = await _wrap(p, f).chat.completions.create(model="ignored", foo=1)
    assert out == "P"
    assert p.seen[0]["model"] == "p-model"
    assert f.seen == []


async def test_fallback_on_primary_error():
    p, f = _Boom(), _OK("F")
    out = await _wrap(p, f).chat.completions.create(model="ignored")
    assert out == "F"
    assert f.seen[0]["model"] == "f-model"


async def test_both_fail_raises():
    c = _wrap(_Boom(), _Boom())
    try:
        await c.chat.completions.create(model="x")
    except RuntimeError as e:
        assert str(e) == "primary down"
    else:
        raise AssertionError("should have raised")


async def test_aclose_closes_both():
    p, f = _OK("P"), _OK("F")
    await _wrap(p, f).aclose()
    assert p.closed and f.closed
