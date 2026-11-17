"""Shared HTTP utilities for collection plugins."""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_USER_AGENT = "SocialListeningBot/1.0 (+https://github.com/social-listening)"


def get_session(
    max_retries: int = 3,
    backoff_factor: float = 0.5,
    user_agent: str = DEFAULT_USER_AGENT,
) -> requests.Session:
    """Create a configured requests.Session with retries on 5xx status codes and timeouts only."""
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})

    # Retry on 500, 502, 503, 504 and connection/read errors
    retries = Retry(
        total=max_retries,
        backoff_factor=backoff_factor,
        status_forcelist=[500, 502, 503, 504],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

