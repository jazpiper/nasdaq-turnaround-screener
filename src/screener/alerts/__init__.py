"""Alert helpers and shared alert-sidecar exceptions."""


class AlertSidecarError(RuntimeError):
    """Raised when alert sidecar generation fails after raw artifacts are written."""

from .builder import build_daily_alert_document
from .state import AlertState, DigestAlertState, TickerAlertState, load_alert_state, save_alert_state

__all__ = [
    "AlertSidecarError",
    "AlertState",
    "DigestAlertState",
    "build_daily_alert_document",
    "TickerAlertState",
    "load_alert_state",
    "save_alert_state",
]
