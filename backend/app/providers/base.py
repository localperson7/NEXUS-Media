from abc import ABC, abstractmethod
from typing import List, Optional
import httpx

from app.models import MediaInspectResponse, MediaType, ProviderInfo


class ProviderError(Exception):
    """Structured error raised by media providers."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class BaseMediaProvider(ABC):
    provider_id: str
    display_name: str
    domains: List[str]
    supported_types: List[MediaType]
    status_label: str = "active"
    notes: str = ""

    @abstractmethod
    def matches(self, url: str, content_type: Optional[str] = None) -> bool:
        """Return True if this provider handles the given URL or content type."""

    @abstractmethod
    async def inspect(
        self,
        url: str,
        headers: Optional[httpx.Headers] = None,
    ) -> MediaInspectResponse:
        """Inspect media metadata and available export options without downloading the full payload."""

    def to_info(self) -> ProviderInfo:
        return ProviderInfo(
            id=self.provider_id,
            name=self.display_name,
            domains=self.domains,
            supported_types=self.supported_types,
            status=self.status_label,
            notes=self.notes,
        )
