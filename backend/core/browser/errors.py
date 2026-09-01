"""Browser engine errors shared by backends and blocks."""

from __future__ import annotations


class BrowserError(RuntimeError):
    """Base error for browser engine failures."""


class BrowserTimeoutError(BrowserError):
    """A CDP command / navigation / wait exceeded its deadline."""


class BrowserEvalError(BrowserError):
    """In-page JavaScript raised or returned exceptionDetails."""


class BrowserSessionClosedError(BrowserError):
    """Operation attempted on a closed or dead browser session."""
