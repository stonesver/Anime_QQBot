from enum import StrEnum

import httpx


class ProviderErrorKind(StrEnum):
    RATE_LIMITED = "rate_limited"
    TEMPORARY = "temporary"
    PERMANENT = "permanent"
    INVALID_RESPONSE = "invalid_response"


class ProviderError(RuntimeError):
    def __init__(self, kind: ProviderErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def raise_for_provider_response(response: httpx.Response) -> None:
    if response.status_code == 429:
        raise ProviderError(ProviderErrorKind.RATE_LIMITED, "provider rate limit reached")
    if response.status_code >= 500:
        raise ProviderError(ProviderErrorKind.TEMPORARY, "provider is temporarily unavailable")
    if response.status_code >= 400:
        raise ProviderError(ProviderErrorKind.PERMANENT, "provider rejected the request")
