from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Protocol


class SupportsFetch(Protocol):
    provider_name: str

    def fetch(self, tickers: Iterable[str]) -> Any:
        """Return a FetchResult-like object."""


@dataclass(frozen=True)
class MarketDataSourceStatus:
    provider: str
    role: str
    status: str
    attempted_ticker_count: int
    successful_ticker_count: int
    failed_ticker_count: int
    error_kind: str | None = None
    rate_limited: bool = False
    retry_count: int = 0
    used_cache: bool = False
    used_stale_cache: bool = False
    cooldown_active: bool = False
    fallback_provider: str | None = None
    message: str | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "provider": self.provider,
            "role": self.role,
            "status": self.status,
            "attempted_ticker_count": self.attempted_ticker_count,
            "successful_ticker_count": self.successful_ticker_count,
            "failed_ticker_count": self.failed_ticker_count,
            "rate_limited": self.rate_limited,
            "retry_count": self.retry_count,
            "used_cache": self.used_cache,
            "used_stale_cache": self.used_stale_cache,
            "cooldown_active": self.cooldown_active,
        }
        if self.error_kind:
            payload["error_kind"] = self.error_kind
        if self.fallback_provider:
            payload["fallback_provider"] = self.fallback_provider
        if self.message:
            payload["message"] = sanitize_provider_message(self.message)
        return payload


class MarketDataRateLimitError(RuntimeError):
    """Raised for provider rate-limit or daily-credit exhaustion responses."""

    def __init__(self, message: str = "rate_limited", *, retry_after_seconds: float | None = None) -> None:
        super().__init__(sanitize_provider_message(message))
        self.retry_after_seconds = retry_after_seconds


_SECRET_QUERY_RE = re.compile(r"(?i)([?&](?:api[_-]?key|apikey|token|access[_-]?token|password|secret|bearer)=)[^&\s]+")
_URL_RE = re.compile(r"https?://[^\s)]+")
_LONG_TOKEN_RE = re.compile(r"(?i)\b(?:api[_-]?key|apikey|token|password|secret|bearer|credential)\b\s*[:=]\s*[^\s,;]+")
_RATE_LIMIT_MARKERS = (
    "429",
    "rate limit",
    "rate_limit",
    "rate-limited",
    "too many requests",
    "run out of api credits",
    "current limit being",
    "daily api credits",
)
_TIMEOUT_MARKERS = ("timeout", "timed out")
_UNAVAILABLE_MARKERS = ("connection", "unavailable", "temporarily", "dns", "network", "refused", "reset")


def normalize_ticker_list(tickers: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for ticker in tickers:
        value = str(ticker).strip().upper()
        if value:
            normalized.append(value)
    return normalized


def sanitize_provider_message(value: object, *, max_length: int = 160) -> str:
    text = str(value or "provider_error")
    text = _SECRET_QUERY_RE.sub(r"\1[redacted]", text)
    text = _URL_RE.sub(_redact_url, text)
    text = _LONG_TOKEN_RE.sub(lambda match: match.group(0).split(":", 1)[0].split("=", 1)[0] + "=[redacted]", text)
    text = re.sub(r"(?i)\buser-agent\b[^\r\n;]*", "User-Agent=[redacted]", text)
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[redacted_email]", text)
    text = text.replace("\n", " ").replace("\r", " ").strip()
    if not text:
        return "provider_error"
    if len(text) > max_length:
        return text[: max_length - 1].rstrip() + "…"
    return text


def classify_provider_error(value: object) -> str:
    text = str(value or "").lower()
    if any(marker in text for marker in _RATE_LIMIT_MARKERS):
        return "rate_limited"
    if any(marker in text for marker in _TIMEOUT_MARKERS):
        return "timeout"
    if any(marker in text for marker in _UNAVAILABLE_MARKERS):
        return "unavailable"
    return "provider_error"


def is_rate_limit_error(value: object) -> bool:
    return isinstance(value, MarketDataRateLimitError) or classify_provider_error(value) == "rate_limited"


def build_source_status(
    *,
    provider: str,
    role: str,
    attempted: int,
    successful: int,
    failed: int,
    retry_count: int = 0,
    used_cache: bool = False,
    used_stale_cache: bool = False,
    cooldown_active: bool = False,
    message: object | None = None,
    fallback_provider: str | None = None,
) -> MarketDataSourceStatus:
    error_kind = classify_provider_error(message) if failed or message else None
    if attempted == 0:
        status = "skipped"
    elif failed == 0:
        status = "ok"
    elif successful > 0:
        status = "partial_success"
    elif error_kind == "rate_limited":
        status = "rate_limited"
    else:
        status = "failed"
    return MarketDataSourceStatus(
        provider=provider,
        role=role,
        status=status,
        attempted_ticker_count=attempted,
        successful_ticker_count=successful,
        failed_ticker_count=failed,
        error_kind=error_kind,
        rate_limited=error_kind == "rate_limited",
        retry_count=retry_count,
        used_cache=used_cache,
        used_stale_cache=used_stale_cache,
        cooldown_active=cooldown_active,
        fallback_provider=fallback_provider,
        message=sanitize_provider_message(message) if message else None,
    )


def derive_market_data_reliability_label(provider_statuses: list[dict[str, Any]]) -> str:
    """Map provider statuses to the compact reliability label used in artifacts."""

    if not provider_statuses:
        return "unofficial"

    if any(bool(status.get("used_stale_cache")) for status in provider_statuses):
        return "stale"

    successful = [status for status in provider_statuses if int(status.get("successful_ticker_count") or 0) > 0]
    if not successful:
        return "partial"

    api_successful = [status for status in successful if str(status.get("provider") or "").lower() not in {"yfinance", "yf"}]
    yfinance_successful = any(str(status.get("provider") or "").lower() in {"yfinance", "yf"} for status in successful)

    if len(api_successful) >= 2:
        return "api-cross-checked"

    if len(api_successful) == 1:
        if yfinance_successful:
            return "fallback"
        if any(str(status.get("role") or "").lower() == "fallback" for status in successful):
            return "fallback"
        return "single-api"

    if yfinance_successful:
        return "unofficial"

    return "partial"


@dataclass
class _CacheEntry:
    value: Any
    stored_at: float


class ProviderResilienceState:
    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        self.clock = clock or time.monotonic
        self._cache: dict[tuple[object, ...], _CacheEntry] = {}
        self._cooldown_until: dict[tuple[object, ...], float] = {}

    def get_cache(self, key: tuple[object, ...], *, ttl_seconds: float, stale_ttl_seconds: float) -> tuple[Any | None, bool]:
        entry = self._cache.get(key)
        if entry is None:
            return None, False
        age = self.clock() - entry.stored_at
        if age <= ttl_seconds:
            return entry.value, False
        if age <= stale_ttl_seconds:
            return entry.value, True
        return None, False

    def set_cache(self, key: tuple[object, ...], value: Any) -> None:
        self._cache[key] = _CacheEntry(value=value, stored_at=self.clock())

    def is_cooling_down(self, key: tuple[object, ...]) -> bool:
        until = self._cooldown_until.get(key)
        if until is None:
            return False
        if until <= self.clock():
            self._cooldown_until.pop(key, None)
            return False
        return True

    def start_cooldown(self, key: tuple[object, ...], seconds: float) -> None:
        if seconds <= 0:
            return
        self._cooldown_until[key] = self.clock() + seconds


DEFAULT_RESILIENCE_STATE = ProviderResilienceState()


def retry_with_backoff(
    call: Callable[[], Any],
    *,
    max_retries: int,
    initial_backoff_seconds: float,
    max_backoff_seconds: float,
    sleeper: Callable[[float], None],
) -> tuple[Any, int]:
    attempts = 0
    while True:
        try:
            return call(), attempts
        except Exception as exc:
            if not is_rate_limit_error(exc) or attempts >= max_retries:
                raise
            attempts += 1
            retry_after = getattr(exc, "retry_after_seconds", None)
            delay = float(retry_after) if retry_after else initial_backoff_seconds * (2 ** (attempts - 1))
            sleeper(max(0.0, min(delay, max_backoff_seconds)))


def _redact_url(match: re.Match[str]) -> str:
    value = match.group(0)
    return value.split("?", 1)[0] + "?[redacted_query]" if "?" in value else "[redacted_url]"
