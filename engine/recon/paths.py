from __future__ import annotations

from urllib.parse import urlsplit


def normalize_endpoint_path(path: str) -> str:
    clean_path = urlsplit(path).path
    segments = clean_path.split("/")
    try:
        booking_index = segments.index("bookings")
    except ValueError:
        return clean_path
    if booking_index + 1 < len(segments) and segments[booking_index + 1]:
        segments[booking_index + 1] = "{id}"
    return "/".join(segments)
