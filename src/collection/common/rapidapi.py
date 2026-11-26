"""Shared client for APIs bought through the RapidAPI marketplace.

Every RapidAPI listing is called the same way: HTTPS to ``https://<host>/<path>``
with two headers, ``x-rapidapi-key`` (one key per RapidAPI account, read from
the ``RAPIDAPI_KEY`` environment variable) and ``x-rapidapi-host`` (the
listing's host). Connectors for individual listings use this client and only
deal with their own request body and response fields.

Errors come back as ``(AttemptStatus, reason)`` so connectors can put them
straight into a CollectionAttempt. The key never appears in a reason.
"""
from dataclasses import dataclass
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

import requests

from src.collection.common.http import get_session
from src.contracts.enums import AttemptStatus

logger = logging.getLogger(__name__)

RAPIDAPI_KEY_ENV = "RAPIDAPI_KEY"
QUOTA_REMAINING_HEADER = "x-ratelimit-requests-remaining"


def get_rapidapi_key() -> Optional[str]:
    """Return the RapidAPI key from the environment, or None when unset/blank."""
    key = os.environ.get(RAPIDAPI_KEY_ENV, "").strip()
    return key or None


@dataclass
class RapidAPIResult:
    """Outcome of one RapidAPI call.

    data: parsed JSON body on success, else None.
    error: (status, reason) on failure, else None.
    quota_remaining: requests left in the current plan period, when RapidAPI sent it.
    """

    data: Any = None
    error: Optional[Tuple[AttemptStatus, str]] = None
    quota_remaining: Optional[int] = None
    http_status: Optional[int] = None

    @property
    def ok(self) -> bool:
        return self.error is None


class RapidAPIClient:
    """Calls one RapidAPI listing (one host) with retries and quota tracking."""

    def __init__(
        self,
        host: str,
        api_name: str,
        session: Optional[requests.Session] = None,
        timeout: float = 60.0,
        max_retries: int = 1,
    ):
        self.host = host.strip()
        self.api_name = api_name
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = session or get_session(max_retries=0)

    @property
    def base_url(self) -> str:
        return f"https://{self.host}"

    def post(self, path: str, body: Dict[str, Any]) -> RapidAPIResult:
        return self._request("POST", path, json_body=body)

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> RapidAPIResult:
        return self._request("GET", path, params=params)

    def _redact(self, text: str, key: str) -> str:
        return text.replace(key, "[REDACTED]") if key and key in text else text

    def _request(
        self,
        method: str,
        path: str,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> RapidAPIResult:
        key = get_rapidapi_key()
        if not key:
            return RapidAPIResult(
                error=(AttemptStatus.failed, f"{RAPIDAPI_KEY_ENV} missing")
            )

        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {
            "x-rapidapi-key": key,
            "x-rapidapi-host": self.host,
            "Content-Type": "application/json",
        }

        last_error: Tuple[AttemptStatus, str] = (
            AttemptStatus.failed,
            f"{self.api_name}: failed after retries",
        )
        for attempt_idx in range(self.max_retries + 1):
            try:
                resp = self._session.request(
                    method,
                    url,
                    headers=headers,
                    json=json_body,
                    params=params,
                    timeout=self.timeout,
                )
            except (requests.Timeout, requests.ConnectionError) as net_err:
                last_error = (
                    AttemptStatus.failed,
                    f"{self.api_name}: network error ({net_err.__class__.__name__})",
                )
                if attempt_idx < self.max_retries:
                    time.sleep(0.5 * (2**attempt_idx))
                    continue
                return RapidAPIResult(error=last_error)
            except requests.RequestException as req_err:
                reason = self._redact(f"{self.api_name}: request error ({req_err})", key)
                return RapidAPIResult(error=(AttemptStatus.failed, reason))

            quota = _parse_int(resp.headers.get(QUOTA_REMAINING_HEADER))
            status = resp.status_code

            if status == 429:
                return RapidAPIResult(
                    error=(
                        AttemptStatus.rate_limited,
                        f"{self.api_name}: RapidAPI quota or rate limit reached (HTTP 429)",
                    ),
                    quota_remaining=quota,
                    http_status=status,
                )
            if status in (401, 403):
                return RapidAPIResult(
                    error=(
                        AttemptStatus.failed,
                        f"{self.api_name}: RapidAPI key rejected or not subscribed to this API "
                        f"(HTTP {status})",
                    ),
                    quota_remaining=quota,
                    http_status=status,
                )
            if status >= 500:
                last_error = (
                    AttemptStatus.failed,
                    f"{self.api_name}: provider server error (HTTP {status})",
                )
                if attempt_idx < self.max_retries:
                    time.sleep(0.5 * (2**attempt_idx))
                    continue
                return RapidAPIResult(error=last_error, quota_remaining=quota, http_status=status)
            if status >= 400:
                detail = _short_message(resp)
                reason = f"{self.api_name}: request rejected (HTTP {status})"
                if detail:
                    reason += f": {detail}"
                return RapidAPIResult(
                    error=(AttemptStatus.failed, self._redact(reason, key)),
                    quota_remaining=quota,
                    http_status=status,
                )

            try:
                data = resp.json()
            except ValueError:
                return RapidAPIResult(
                    error=(AttemptStatus.failed, f"{self.api_name}: response was not JSON"),
                    quota_remaining=quota,
                    http_status=status,
                )
            return RapidAPIResult(data=data, quota_remaining=quota, http_status=status)

        return RapidAPIResult(error=last_error)


def _parse_int(value: Optional[str]) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _short_message(resp: requests.Response, limit: int = 200) -> str:
    """Provider's error message, trimmed, for the attempt reason."""
    try:
        body = resp.json()
        if isinstance(body, dict):
            msg = body.get("message") or body.get("error") or ""
            return str(msg)[:limit]
    except ValueError:
        pass
    return (resp.text or "")[:limit]
