from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from findbrokenlinks.models import LinkRef


class Extractor(ABC):
    @abstractmethod
    def extract(self, body: str, source_page: str) -> Iterable[LinkRef]: ...
