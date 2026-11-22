from typing import List, Optional
import httpx

from app.models import MediaInspectResponse, ProviderInfo
from app.providers.base import BaseMediaProvider
from app.providers.direct import DirectMediaProvider
from app.providers.ytdlp_provider import (
    CompatibleWebProvider,
    InstagramProvider,
    PinterestProvider,
    TikTokProvider,
    YouTubeProvider,
)


class ProviderRegistry:
    """Ordered registry of media providers."""

    def __init__(self) -> None:
        self.direct_provider = DirectMediaProvider()
        self.platform_providers: List[BaseMediaProvider] = [
            YouTubeProvider(),
            TikTokProvider(),
            InstagramProvider(),
            PinterestProvider(),
        ]
        self.fallback_provider = CompatibleWebProvider()

    def list_providers(self) -> List[ProviderInfo]:
        all_providers: List[BaseMediaProvider] = [
            self.direct_provider,
            *self.platform_providers,
            self.fallback_provider,
        ]
        return [p.to_info() for p in all_providers]

    def resolve_provider(
        self,
        url: str,
        content_type: Optional[str] = None,
    ) -> BaseMediaProvider:
        # 1. Check dedicated platform providers first (YouTube, TikTok, Instagram, Pinterest)
        for provider in self.platform_providers:
            if provider.matches(url, content_type):
                return provider

        # 2. Check direct media file link by URL extension or HTTP Content-Type
        if self.direct_provider.matches(url, content_type):
            return self.direct_provider

        # 3. Fallback to generic yt-dlp compatible provider
        return self.fallback_provider

    async def inspect_url(
        self,
        url: str,
        headers: Optional[httpx.Headers] = None,
    ) -> MediaInspectResponse:
        content_type = headers.get("content-type") if headers else None
        provider = self.resolve_provider(url, content_type)
        return await provider.inspect(url, headers=headers)


provider_registry = ProviderRegistry()
