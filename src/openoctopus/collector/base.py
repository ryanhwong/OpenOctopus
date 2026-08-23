from typing import ClassVar, Protocol

from openoctopus.models import RawProduct


class SourceAdapter(Protocol):
    platform: ClassVar[str]
    async def fetch(self, url: str) -> RawProduct: ...


_REGISTRY: list[type] = []


def register(cls: type) -> type:
    _REGISTRY.append(cls)
    return cls


def get_adapter(url: str):
    for cls in _REGISTRY:
        if cls.matches(url):
            return cls()
    raise ValueError(f"no adapter matches {url}")
