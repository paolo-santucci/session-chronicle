"""Versioned identities; legacy bare identifiers are never assigned a harness."""
import base64
import binascii

HARNESSES = ("opencode", "claude-code", "codex", "pi")


class AmbiguousIdentity(ValueError):
    pass


def canonical_identity(identity):
    if (not isinstance(identity, dict) or set(identity) != {"schema_version", "harness", "session_id"}
            or type(identity.get("schema_version")) is not int or identity["schema_version"] != 1
            or identity.get("harness") not in HARNESSES):
        raise ValueError("Invalid versioned session identity")
    native = identity.get("session_id")
    if not isinstance(native, str) or not native.strip() or "\0" in native:
        raise ValueError("Native session identity must be non-empty text without NUL")
    encoded = base64.urlsafe_b64encode(native.encode("utf-8")).decode("ascii").rstrip("=")
    return f"chronicle:v1:{identity['harness']}:{encoded}"


def parse_identity(value):
    if not isinstance(value, str):
        raise ValueError("Qualified session identity must be text")
    parts = value.split(":")
    if len(parts) != 4 or parts[:2] != ["chronicle", "v1"]:
        raise ValueError("Invalid qualified session identity")
    try:
        native = base64.b64decode(parts[3] + "=" * (-len(parts[3]) % 4), altchars=b"-_", validate=True).decode("utf-8")
    except (ValueError, UnicodeError, binascii.Error) as error:
        raise ValueError("Invalid qualified session identity encoding") from error
    identity = {"schema_version": 1, "harness": parts[2], "session_id": native}
    if canonical_identity(identity) != value:
        raise ValueError("Noncanonical qualified session identity")
    return identity
