"""Thread-safe budget tracking for collection requests and platforms."""
from dataclasses import dataclass
from datetime import datetime, timezone
import os
import threading
import uuid
from typing import Any, Dict, Optional, Union

from config.settings import load_config
from src.contracts.enums import AttemptStatus, Method, Platform
from src.contracts.schemas import CollectionAttempt


class BudgetExceeded(Exception):
    """Raised when an operation requests funds exceeding remaining budget."""


@dataclass
class ReservationToken:
    """Token representing reserved budget funds."""
    token_id: str
    platform: Platform
    reserved_amount: float


class BudgetTracker:
    """Thread-safe tracker for collection budget spend across platforms."""

    def __init__(self, limit_usd: Optional[float] = None):
        if limit_usd is not None:
            self.limit_usd = float(limit_usd)
        elif "BUDGET_USD" in os.environ:
            try:
                self.limit_usd = float(os.environ["BUDGET_USD"])
            except ValueError:
                self.limit_usd = float(load_config().get("budget_usd", 10.0))
        else:
            self.limit_usd = float(load_config().get("budget_usd", 10.0))

        self.spent_total: float = 0.0
        self.spent_by_platform: Dict[str, float] = {}
        self._reserved_total: float = 0.0
        self._reservations: Dict[str, ReservationToken] = {}
        self._lock = threading.Lock()

    def _effective_platform(self, platform: Union[Platform, str]) -> str:
        if isinstance(platform, Platform):
            return platform.value
        return str(platform)

    def can_afford(self, platform: Union[Platform, str], amount: float) -> bool:
        """Check if amount can be afforded within remaining limit."""
        if amount <= 0.0:
            return True
        with self._lock:
            remaining = self.limit_usd - (self.spent_total + self._reserved_total)
            return amount <= remaining

    def reserve(self, platform: Union[Platform, str], amount: float) -> ReservationToken:
        """Reserve an estimated spend amount. Free calls (0.0) always pass."""
        if amount < 0.0:
            raise ValueError("Reservation amount cannot be negative")

        plat_enum = platform if isinstance(platform, Platform) else Platform(str(platform))

        with self._lock:
            if amount > 0.0:
                remaining = self.limit_usd - (self.spent_total + self._reserved_total)
                if amount > remaining:
                    raise BudgetExceeded(
                        f"Cannot reserve ${amount:.4f}: only ${remaining:.4f} remaining of ${self.limit_usd:.4f}"
                    )
                self._reserved_total += amount

            token = ReservationToken(
                token_id=f"res_{uuid.uuid4().hex[:12]}",
                platform=plat_enum,
                reserved_amount=amount,
            )
            self._reservations[token.token_id] = token
            return token

    def commit(self, token: ReservationToken, actual_amount: float) -> None:
        """Commit actual spend against a reserved token, releasing any difference."""
        if actual_amount < 0.0:
            raise ValueError("Actual amount cannot be negative")

        with self._lock:
            res = self._reservations.pop(token.token_id, None)
            if not res:
                return

            self._reserved_total = max(0.0, self._reserved_total - res.reserved_amount)
            self.spent_total += actual_amount

            plat_key = self._effective_platform(res.platform)
            self.spent_by_platform[plat_key] = self.spent_by_platform.get(plat_key, 0.0) + actual_amount

    def release(self, token: ReservationToken) -> None:
        """Release a previously reserved token without spending."""
        with self._lock:
            res = self._reservations.pop(token.token_id, None)
            if not res:
                return
            self._reserved_total = max(0.0, self._reserved_total - res.reserved_amount)

    def snapshot(self) -> Dict[str, Any]:
        """Return a snapshot dict of budget limits and spend."""
        with self._lock:
            remaining = max(0.0, self.limit_usd - (self.spent_total + self._reserved_total))
            return {
                "limit_usd": round(self.limit_usd, 4),
                "spent_total": round(self.spent_total, 4),
                "reserved_total": round(self._reserved_total, 4),
                "remaining_usd": round(remaining, 4),
                "spent_by_platform": {k: round(v, 4) for k, v in self.spent_by_platform.items()},
            }

    def create_exhausted_attempt(
        self,
        company: str,
        platform: Platform,
        method: Method,
        reason: Optional[str] = None,
    ) -> CollectionAttempt:
        """Generate a standardized CollectionAttempt with budget_exhausted status."""
        now = datetime.now(timezone.utc)
        return CollectionAttempt(
            company=company,
            platform=platform,
            method=method,
            status=AttemptStatus.budget_exhausted,
            reason=reason or f"Budget limit of ${self.limit_usd:.2f} reached",
            item_count=0,
            cost_usd=0.0,
            started_at=now,
            finished_at=now,
            scraping_checks=None,
        )
