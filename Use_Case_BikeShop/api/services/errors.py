"""
Errors raised by the shop services.

Services know nothing about HTTP (SPEC §8.3: tools can call them in-process).
They raise one of these; `main.py` turns them into `{"detail": message}`
with the matching status code. Messages are sentences a customer can read.
"""


class ShopError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class RuleViolation(ShopError):
    """A shop rule is broken: opening hours, time grid, duration (400)."""
    status_code = 400


class NotAllowed(ShopError):
    """The caller may not do this (403)."""
    status_code = 403


class NotFound(ShopError):
    """Doesn't exist, or isn't yours to see (404)."""
    status_code = 404


class Conflict(ShopError):
    """The state doesn't allow it: bike taken, wrong status, limit reached (409)."""
    status_code = 409


class InvalidInput(ShopError):
    """Input is well-formed but makes no sense, e.g. daily > 24 x hourly (422)."""
    status_code = 422
