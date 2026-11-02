"""Pure URL/key binding rules for provider model and connection probes.

Never read a stored credential until the requested destination has matched the
provider's saved API base URL. This is separate from SSRF/authorization checks.
"""

from urllib.parse import urlsplit


class UntrustedProbeTarget(ValueError):
    """The request tries to reuse a stored key outside its saved destination."""


def canonical_api_base(value):
    """Return a strict (scheme, host, port, path) identity for an API base URL."""
    value = str(value or "").strip()
    if not value or any(ord(ch) < 33 or ord(ch) == 127 for ch in value):
        raise ValueError("Invalid API base URL")
    try:
        parsed = urlsplit(value)
        if (parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or "?" in value or "#" in value):
            raise ValueError("Invalid API base URL")
        port = parsed.port
        if port is not None and not (1 <= port <= 65535):
            raise ValueError("Invalid API port")
        host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        if not host:
            raise ValueError("Invalid API host")
        port = port if port is not None else (443 if parsed.scheme.lower() == "https" else 80)
        return (parsed.scheme.lower(), host, port, parsed.path.rstrip("/") or "/")
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Invalid API base URL") from exc


def resolve_probe_key(explicit_key, requested_base, provider_id, providers, key_reader):
    """Use a supplied temporary key or a stored key bound to this exact API base.

    key_reader is only called AFTER a saved provider's target has matched.
    Unknown/disabled providers do not get any saved key.
    """
    explicit = str(explicit_key or "").strip()
    if explicit:
        return explicit
    provider_id = str(provider_id or "").strip().lower()
    if not provider_id:
        return ""
    provider = next((p for p in providers if str(p.get("id") or "").strip().lower() == provider_id), None)
    if not provider or not provider.get("enabled", True):
        return ""
    try:
        if canonical_api_base(requested_base) != canonical_api_base(provider.get("base_url")):
            raise UntrustedProbeTarget("A temporary API key is required for a different Base URL")
    except ValueError as exc:
        raise UntrustedProbeTarget("A temporary API key is required for a different Base URL") from exc
    return key_reader(provider_id)
