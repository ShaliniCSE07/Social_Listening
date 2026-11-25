"""User-chosen platform filter ("only collect from Instagram, Google, ...").

An empty filter means "collect from everything". Known names and common
spellings ("insta", "fb", "linked in", "x") resolve to ``Platform`` values and
match a mention's platform exactly. Anything else ("play store") is kept as
free text and matches when it appears in a source/dataset name or in a
dataset row's own platform column.
"""
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional, Set, Tuple

from src.contracts.enums import Platform

MAX_FILTER_ENTRIES = 20
MAX_ENTRY_LENGTH = 50

_ALIASES = {
    "instagram": Platform.instagram, "insta": Platform.instagram, "ig": Platform.instagram,
    "facebook": Platform.facebook, "fb": Platform.facebook, "meta": Platform.facebook,
    "linkedin": Platform.linkedin, "linked in": Platform.linkedin,
    "google": Platform.google, "google reviews": Platform.google, "google maps": Platform.google,
    "google places": Platform.google,
    "tripadvisor": Platform.tripadvisor, "trip advisor": Platform.tripadvisor,
    "reddit": Platform.reddit,
    "twitter": Platform.twitter_x, "x": Platform.twitter_x, "twitter x": Platform.twitter_x,
    "twitter/x": Platform.twitter_x, "twitter_x": Platform.twitter_x,
    "news": Platform.news_blog, "blog": Platform.news_blog, "blogs": Platform.news_blog,
    "news blog": Platform.news_blog, "news/blogs": Platform.news_blog, "news_blog": Platform.news_blog,
    "other": Platform.other,
}


def _norm(text: Any) -> str:
    """Lowercase and collapse separators: 'Linked-In ' -> 'linked in'."""
    return re.sub(r"[\s_\-]+", " ", str(text or "").strip().lower()).strip()


def resolve_platform(text: Any) -> Optional[Platform]:
    """Map a user-typed or dataset-supplied name to a Platform, if recognised."""
    key = _norm(text)
    if key in _ALIASES:
        return _ALIASES[key]
    squashed = key.replace(" ", "")
    for alias, plat in _ALIASES.items():
        if alias.replace(" ", "") == squashed:
            return plat
    return None


@dataclass
class PlatformFilter:
    requested: List[str] = field(default_factory=list)
    platforms: Set[Platform] = field(default_factory=set)
    free_text: Set[str] = field(default_factory=set)

    @property
    def active(self) -> bool:
        return bool(self.platforms or self.free_text)

    def describe(self) -> str:
        return ", ".join(self.requested)

    def allows_platform(self, platform: Any) -> bool:
        """True if a source/task for this platform should run."""
        if not self.active:
            return True
        plat = platform if isinstance(platform, Platform) else resolve_platform(
            getattr(platform, "value", platform)
        )
        return plat in self.platforms

    def matches_text(self, *labels: Any) -> bool:
        """True if any free-text entry appears in one of the labels (names, row values)."""
        normed = [_norm(lbl) for lbl in labels if lbl]
        return any(ft in lbl for ft in self.free_text for lbl in normed)

    def allows_mention(self, platform: Any, *labels: Any) -> bool:
        """Decide for one collected item.

        ``platform`` is the mention's platform; ``labels`` are extra names that
        describe where it came from (source name, a dataset row's platform).
        A row-level platform that resolves to a known Platform counts as that
        platform too.
        """
        if not self.active:
            return True
        if self.allows_platform(platform):
            return True
        for lbl in labels:
            plat = resolve_platform(lbl)
            if plat is not None and plat in self.platforms:
                return True
        return self.matches_text(*labels)


def parse_platform_filter(values: Optional[Iterable[Any]]) -> PlatformFilter:
    """Build a filter from user input; blank/None entries are ignored.

    Entries may also be comma-separated ("insta, fb").
    """
    pf = PlatformFilter()
    if not values:
        return pf
    seen: Set[str] = set()
    for raw in values:
        for part in str(raw or "").split(","):
            key = _norm(part)[:MAX_ENTRY_LENGTH]
            if not key:
                continue
            plat = resolve_platform(key)
            dedupe_key = plat.value if plat is not None else key  # "insta" == "Instagram"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            pf.requested.append(part.strip()[:MAX_ENTRY_LENGTH])
            if plat is not None:
                pf.platforms.add(plat)
            else:
                pf.free_text.add(key)
            if len(pf.requested) >= MAX_FILTER_ENTRIES:
                return pf
    return pf


def prune_plan_tasks(plan: Any, pf: PlatformFilter, catalogue: Optional[dict] = None) -> List[Tuple[Any, str]]:
    """Remove plan tasks that cannot produce items from the chosen platforms.

    API/scraping tasks are kept only when their platform is in the filter.
    Dataset tasks are kept when the catalogue entry's platform matches, when
    the entry maps a per-row ``platform`` column (filtered row by row later),
    or when a free-text entry matches the dataset's name/key.
    Returns the removed tasks with a human-readable reason.
    """
    if not pf.active:
        return []
    catalogue = catalogue or {}
    kept, removed = [], []
    for task in list(getattr(plan, "tasks", [])):
        dkey = getattr(task, "dataset_key", None)
        if dkey is not None or str(getattr(task, "platform", "")) == "dataset":
            entry = catalogue.get(dkey)
            entry_platform = getattr(entry, "platform", None)
            columns = getattr(entry, "columns", None) or {}
            ok = (
                (entry_platform is not None and pf.allows_platform(entry_platform))
                or bool(columns.get("platform"))
                or pf.matches_text(dkey, getattr(entry, "name", None))
            )
            label = f"dataset '{dkey}' (platform: {entry_platform or 'unknown'})"
        else:
            ok = pf.allows_platform(task.platform)
            label = getattr(task.platform, "value", str(task.platform))
        if ok:
            kept.append(task)
        else:
            removed.append((task, f"Skipped {label}: not in platform filter ({pf.describe()})"))
    plan.tasks = kept
    return removed
