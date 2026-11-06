import hashlib
import hmac
import os

_PEPPER = os.environ.get("SOCL_AUTHOR_PEPPER", "").encode()
if not _PEPPER:
    raise RuntimeError("SOCL_AUTHOR_PEPPER env var is required")


def pseudonymize_author(platform: str, handle: str | None) -> str | None:
    if not handle:
        return None
    msg = f"{platform}:{handle}".encode()
    digest = hmac.new(_PEPPER, msg, hashlib.sha256).hexdigest()
    return f"user_{digest[:8]}"