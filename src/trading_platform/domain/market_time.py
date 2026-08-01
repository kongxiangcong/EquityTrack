from __future__ import annotations

from datetime import timedelta, timezone, tzinfo


SHANGHAI_TIMEZONE_NAME = "Asia/Shanghai"
SHANGHAI_TIMEZONE = timezone(timedelta(hours=8), SHANGHAI_TIMEZONE_NAME)


def supported_market_timezone(name: str) -> tzinfo:
    """Return the deterministic timezone supported by the A-share platform."""
    if name != SHANGHAI_TIMEZONE_NAME:
        raise ValueError("MARKET_TIMEZONE_UNSUPPORTED")
    return SHANGHAI_TIMEZONE


__all__ = [
    "SHANGHAI_TIMEZONE",
    "SHANGHAI_TIMEZONE_NAME",
    "supported_market_timezone",
]
