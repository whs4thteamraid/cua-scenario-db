"""Utilities for normalizing support ticket identifiers."""


def normalize_ticket_id(value: str) -> str:
    """Return a canonical ticket ID.

    This implementation is intentionally incomplete for the repair task.
    See docs/ticket_format.md and tests/test_ticket_utils.py.
    """

    if not isinstance(value, str):
        raise TypeError("ticket ID must be a string")
    return value.strip().upper()

