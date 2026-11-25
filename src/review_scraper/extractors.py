"""Find reviews in an HTML page.

Three strategies, tried in order; the first that yields reviews wins:

1. ``json_ld``   - schema.org ``Review`` objects in <script type="application/ld+json">
2. ``microdata`` - elements marked ``itemtype=".../Review"``
3. ``heuristic`` - repeated blocks whose class/id says review/comment/testimonial

Each review is returned as a plain dict:
``text, title, rating (1-5 or None), rating_raw, best_rating, author, date,
review_id, url, extraction_method``.
"""
import json
import re
from collections import defaultdict
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

MAX_TEXT = 5000
MIN_TEXT = 15

_REVIEW_WORD = re.compile(r"review|comment|testimonial|feedback|opinion", re.I)
_NOT_A_REVIEW = re.compile(
    r"(count|summary|header|heading|form|nav|pagination|pager|filter|sort|button|btn|"
    r"widget-title|write|add-|new-review|tabs?\b|toolbar|histogram|breakdown|stats|avg|average|total|"
    r"overall|search|modal|tooltip|icon|label|link)",
    re.I,
)
# Form validation / UI messages that happen to use words like "feedback"
_UI_MESSAGE_CLASS = re.compile(r"invalid|valid-feedback|error|alert|validation|helper|hint|toast|placeholder|snackbar", re.I)
_UI_MESSAGE_TEXT = re.compile(
    r"^(please (enter|check|select|provide|fill|choose)|this field is required|required field|invalid\b)", re.I
)
# Rating summaries ("98% of the 1,519 user reviews are positive", "based on 120 reviews")
_AGGREGATE_TEXT = re.compile(
    r"\(\s*\d{1,3}\s*% of [\d,.]+\s*\)|\b\d{1,3}\s*% of (the )?[\d,.]+\b|based on [\d,.]+ (user )?(reviews|ratings)|"
    r"[\d,.]+ (user )?(reviews|ratings) (in the last|total|overall)|"
    r"\b(overwhelmingly|very|mostly) (positive|negative)\b|\bmixed reviews\b|"
    r"^(recent|all) reviews\s*:|average (rating|score)|out of [\d,.]+ (reviews|ratings)",
    re.I,
)
_MONTHS = r"(jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|june?|july?|aug(ust)?|sep(t(ember)?)?|oct(ober)?|nov(ember)?|dec(ember)?)"
_DATE_TEXT = re.compile(
    rf"\b{_MONTHS}\.? \d{{1,2}},? \d{{4}}\b|\b\d{{1,2}} {_MONTHS}\.?,? \d{{4}}\b|\b\d{{4}}-\d{{2}}-\d{{2}}\b|"
    rf"\b\d{{1,2}}/\d{{1,2}}/\d{{2,4}}\b|\b\d+ (minute|hour|day|week|month|year)s? ago\b|"
    rf"(?<=posted: )\d{{1,2}} {_MONTHS}\b|(?<=posted: ){_MONTHS} \d{{1,2}}\b",
    re.I,
)
_FORM_TAGS = {"form", "label", "textarea", "select", "option", "input", "fieldset", "legend"}
# Profile clutter around author names: "1,239 reviews", "4 followers", "Follow"
_AUTHOR_CLUTTER = re.compile(
    r"\b[\d,.]+\s*(k\s*)?(reviews?|ratings?|followers?|following|friends?|photos?|helpful votes?|contributions?)\b|"
    r"\b(follow|following|unfollow|verified (buyer|purchase|reviewer)|top reviewer|level \d+ ?(local guide)?)\b",
    re.I,
)

_TEXT_HINT = re.compile(r"body|text|content|comment|description|message|desc", re.I)
_TITLE_HINT = re.compile(r"title|headline|heading|summary-title", re.I)
_AUTHOR_HINT = re.compile(r"author|user|reviewer|name|customer|profile|by-?line|nickname", re.I)
_DATE_HINT = re.compile(r"date|time|posted|published|ago", re.I)
_RATING_HINT = re.compile(r"rating|stars?|score|rate", re.I)

_OUT_OF = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:/|out\s+of|of)\s*(\d+(?:[.,]\d+)?)", re.I)
_N_STARS = re.compile(r"(?:rated\s*)?(\d(?:[.,]\d)?)\s*(?:-|\s)?(?:stars?|★)", re.I)
_RATED_N = re.compile(r"rated\s*(\d(?:[.,]\d)?)", re.I)
_CLASS_NUM = re.compile(r"(?:rating|stars?|score|rate)[-_ ]?(\d{1,2})(?!\d)", re.I)


def _clean(text: Any) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    text = re.sub(r"\s*(read more|show more|see more|more)\s*$", "", text, flags=re.I)
    return text[:MAX_TEXT]


def _num(value: Any) -> Optional[float]:
    try:
        return float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def normalize_rating(value: Any, best: Any = None) -> Optional[float]:
    """Scale a rating to 1-5 (e.g. 8/10 -> 4.0). Returns None if unusable."""
    v = _num(value)
    if v is None:
        return None
    b = _num(best)
    if b and b > 0 and b != 5:
        v = v / b * 5.0
    elif b is None and 5 < v <= 10:
        v = v / 2.0  # unlabeled 10-point score
    elif b is None and 10 < v <= 100:
        v = v / 20.0  # percentage-style widths, e.g. "width: 80%"
    if v < 0.5 or v > 5:
        return None
    return round(max(1.0, v), 2)


def _attrs_text(el: Tag) -> str:
    parts = []
    for key in ("class", "id", "itemprop", "data-testid", "data-test", "data-hook", "role"):
        val = el.get(key)
        if val:
            parts.append(" ".join(val) if isinstance(val, list) else str(val))
    return " ".join(parts)


def _review(text, title=None, rating=None, rating_raw=None, best=None, author=None, date=None,
            review_id=None, url=None, method="heuristic", recommended=None) -> Dict[str, Any]:
    return {
        "recommended": recommended,
        "text": _clean(text),
        "title": _clean(title) or None,
        "rating": rating,
        "rating_raw": rating_raw,
        "best_rating": best,
        "author": _clean(author) or None,
        "date": _clean(date) or None,
        "review_id": str(review_id) if review_id else None,
        "url": url,
        "extraction_method": method,
    }


# ── 1. JSON-LD ──────────────────────────────────────────────────────────

def _types(obj: Dict[str, Any]) -> List[str]:
    t = obj.get("@type", [])
    return [str(x).lower() for x in (t if isinstance(t, list) else [t])]


def _walk(obj: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _name(val: Any) -> Optional[str]:
    if isinstance(val, dict):
        return val.get("name") or val.get("alternateName")
    if isinstance(val, list) and val:
        return _name(val[0])
    return str(val) if val else None


def extract_json_ld(soup: BeautifulSoup, page_url: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    reviews, item_name = [], None
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = (script.string or script.get_text() or "").strip()
        raw = re.sub(r"^\s*<!--|-->\s*$", "", raw)
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        for obj in _walk(data):
            types = _types(obj)
            if not item_name and isinstance(obj.get("review"), (list, dict)) and obj.get("name"):
                item_name = _name(obj.get("name"))
            if "review" in types or any(t.endswith("review") and "aggregate" not in t for t in types):
                text = obj.get("reviewBody") or obj.get("description") or obj.get("text")
                if not text or len(_clean(text)) < MIN_TEXT:
                    continue
                rr = obj.get("reviewRating") or {}
                value = rr.get("ratingValue") if isinstance(rr, dict) else rr
                best = rr.get("bestRating") if isinstance(rr, dict) else None
                if not item_name and obj.get("itemReviewed"):
                    item_name = _name(obj.get("itemReviewed"))
                reviews.append(_review(
                    text, title=obj.get("name") or obj.get("headline"),
                    rating=normalize_rating(value, best), rating_raw=value, best=best,
                    author=_name(obj.get("author")), date=obj.get("datePublished") or obj.get("dateCreated"),
                    review_id=obj.get("@id") or obj.get("identifier"),
                    url=urljoin(page_url, obj["url"]) if isinstance(obj.get("url"), str) else None,
                    method="json_ld",
                ))
    return reviews, item_name


# ── 2. Microdata ────────────────────────────────────────────────────────

def _prop(scope: Tag, name: str) -> Optional[Tag]:
    """First itemprop=name inside scope that is not inside a deeper nested review scope."""
    for el in scope.find_all(attrs={"itemprop": re.compile(rf"(^|\s){name}(\s|$)", re.I)}):
        parent_scope = el.find_parent(attrs={"itemtype": re.compile(r"review", re.I)})
        if parent_scope is scope or parent_scope is None or el is scope:
            return el
    return None


def _prop_value(el: Optional[Tag]) -> Optional[str]:
    if el is None:
        return None
    for attr in ("content", "datetime", "value"):
        if el.get(attr):
            return str(el.get(attr))
    return el.get_text(" ", strip=True)


def extract_microdata(soup: BeautifulSoup, page_url: str) -> List[Dict[str, Any]]:
    out = []
    for scope in soup.find_all(attrs={"itemtype": re.compile(r"schema\.org/(\w+)?review$", re.I)}):
        if "aggregate" in str(scope.get("itemtype", "")).lower():
            continue
        text = _prop_value(_prop(scope, "reviewBody")) or _prop_value(_prop(scope, "description"))
        if not text or len(_clean(text)) < MIN_TEXT:
            continue
        author_el = _prop(scope, "author")
        author = None
        if author_el is not None:
            name_el = author_el.find(attrs={"itemprop": "name"})
            author = _prop_value(name_el) if name_el else _prop_value(author_el)
        value = _prop_value(_prop(scope, "ratingValue"))
        best = _prop_value(_prop(scope, "bestRating"))
        out.append(_review(
            text, title=_prop_value(_prop(scope, "name")) or _prop_value(_prop(scope, "headline")),
            rating=normalize_rating(value, best), rating_raw=value, best=best,
            author=author, date=_prop_value(_prop(scope, "datePublished")),
            review_id=scope.get("id"), method="microdata",
        ))
    return out


# ── 3. Heuristic layout detection ───────────────────────────────────────

def _signature(el: Tag) -> Tuple[str, str]:
    classes = el.get("class") or []
    # Drop per-item variations such as "review-123" or "is-expanded"
    stable = sorted(c for c in classes if not re.search(r"\d{3,}|active|expanded|selected|odd|even|first|last", c))
    return el.name, " ".join(stable) or str(el.get("data-hook") or el.get("data-testid") or el.get("itemprop") or "")


_HIDDEN_CLASS = re.compile(r"^(hidden|a-hidden|aok-hidden|d-none|sr-only|visually-hidden|a-popover-preload|is-hidden)$", re.I)
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)


def _is_hidden(el: Tag) -> bool:
    """True if el or an ancestor is hidden, a pop-up template, or part of a form."""
    for node in [el] + list(el.parents):
        if not isinstance(node, Tag) or node.name in ("body", "html", "[document]"):
            break
        if node.name in ("form", "fieldset", "template"):
            return True
        if node.has_attr("hidden") or str(node.get("aria-hidden", "")).lower() == "true":
            return True
        if _HIDDEN_STYLE.search(str(node.get("style") or "")):
            return True
        if any(_HIDDEN_CLASS.match(c) for c in (node.get("class") or [])):
            return True
    return False


def _candidates(soup: BeautifulSoup) -> List[Tag]:
    out = []
    for el in soup.find_all(True):
        if el.name in ("script", "style", "noscript", "head", "meta", "link", "svg", "button",
                       "nav", "header", "footer", "body", "html", "img", "iframe") or el.name in _FORM_TAGS:
            continue
        attrs = _attrs_text(el)
        if not attrs or not _REVIEW_WORD.search(attrs):
            continue
        if _UI_MESSAGE_CLASS.search(attrs) or _is_hidden(el):
            continue
        # Element named e.g. "review-count" or "comments-header" is not a review itself
        names = attrs.split()
        if all(_NOT_A_REVIEW.search(n) for n in names if _REVIEW_WORD.search(n)):
            continue
        out.append(el)
    return out


def _find_hinted(item: Tag, hint: re.Pattern, tags=None) -> Optional[Tag]:
    for el in item.find_all(tags or True):
        if el is item:
            continue
        if hint.search(_attrs_text(el)):
            return el
    return None


def extract_rating_from(item: Tag) -> Tuple[Optional[float], Optional[str], Optional[str]]:
    """Look for a star rating in an element. Returns (rating_1_to_5, raw_value, best)."""
    els = [item] + [e for e in item.find_all(True)]
    for el in els:
        attr_blob = _attrs_text(el)
        rating_like = bool(_RATING_HINT.search(attr_blob)) or el.name == "img"
        # data-rating / data-score / aria-valuenow
        for key in ("data-rating", "data-score", "data-stars", "data-value", "aria-valuenow"):
            if el.get(key) and (rating_like or key.startswith("data-r") or key.startswith("data-s")):
                best = el.get("aria-valuemax") or el.get("data-best") or el.get("data-max")
                r = normalize_rating(el.get(key), best)
                if r:
                    return r, str(el.get(key)), best
        # aria-label / title / alt like "4 out of 5 stars", "Rated 4.5"
        for key in ("aria-label", "title", "alt"):
            txt = el.get(key)
            if not txt or not (rating_like or re.search(r"star|rated|out of", str(txt), re.I)):
                continue
            m = _OUT_OF.search(txt)
            if m:
                r = normalize_rating(m.group(1), m.group(2))
                if r:
                    return r, m.group(1), m.group(2)
            m = _N_STARS.search(txt) or _RATED_N.search(txt)
            if m:
                r = normalize_rating(m.group(1), 5)
                if r:
                    return r, m.group(1), "5"
        if rating_like:
            # class like "rating-4", "stars-45" (=4.5), "star-rating-5"
            m = _CLASS_NUM.search(attr_blob)
            if m:
                n = int(m.group(1))
                val = n / 10 if n > 5 and n <= 50 else n
                r = normalize_rating(val, 5)
                if r:
                    return r, m.group(1), "5"
            # inline style width:80%
            style = el.get("style") or ""
            m = re.search(r"width\s*:\s*(\d{1,3}(?:\.\d+)?)%", style)
            if m:
                r = normalize_rating(float(m.group(1)) / 20.0, 5)
                if r:
                    return r, m.group(1) + "%", "100%"
            # text like "4/5" or "★★★★☆"
            txt = el.get_text(" ", strip=True)
            if txt and len(txt) <= 40:
                filled = txt.count("★")
                if filled and filled + txt.count("☆") <= 10:
                    r = normalize_rating(filled, filled + txt.count("☆") or 5)
                    if r:
                        return r, str(filled), str(filled + txt.count("☆"))
                m = _OUT_OF.search(txt)
                if m:
                    r = normalize_rating(m.group(1), m.group(2))
                    if r:
                        return r, m.group(1), m.group(2)
                m = _N_STARS.search(txt)
                if m:
                    r = normalize_rating(m.group(1), 5)
                    if r:
                        return r, m.group(1), "5"
            # count filled star icons: class contains star + full/filled/on/active
            stars = [s for s in el.find_all(True) if re.search(r"star", _attrs_text(s), re.I)]
            if 3 <= len(stars) <= 10:
                full = sum(1 for s in stars if re.search(r"full|filled|on\b|active|checked|fa-star(?!-o|-half)", _attrs_text(s), re.I))
                half = sum(1 for s in stars if re.search(r"half", _attrs_text(s), re.I))
                if full:
                    r = normalize_rating(full + 0.5 * half, len(stars) if len(stars) != 5 else 5)
                    if r:
                        return r, str(full + 0.5 * half), str(len(stars))
    return None, None, None


def _pick_text_el(item: Tag) -> Optional[Tag]:
    """The most specific text-like element: drill into hinted children that hold
    most (>=80%) of the text, so wrappers that add dates/profiles are skipped."""
    hinted = [
        el for el in item.find_all(["p", "div", "span", "q", "blockquote", "section", "article"])
        if el is not item and _TEXT_HINT.search(_attrs_text(el))
        and not _AUTHOR_HINT.search(_attrs_text(el))
        and len(el.get_text(" ", strip=True)) >= MIN_TEXT
    ]
    if not hinted:
        return None
    longest = max(hinted, key=lambda e: len(e.get_text(" ", strip=True)))
    longest_len = len(longest.get_text(" ", strip=True))
    # Innermost text blocks (no hinted block inside them) are usually the review body itself
    leaves = [e for e in hinted if not any(o is not e and e in o.parents for o in hinted)]
    leaf = max(leaves, key=lambda e: len(e.get_text(" ", strip=True)))
    if len(leaf.get_text(" ", strip=True)) >= 0.5 * longest_len:
        return leaf
    # Body split over several small blocks: drill down only while one child holds most of it
    best = longest
    while True:
        best_len = len(best.get_text(" ", strip=True))
        inner = [e for e in hinted if e is not best and best in e.parents
                 and len(e.get_text(" ", strip=True)) >= 0.8 * best_len]
        if not inner:
            return best
        best = max(inner, key=lambda e: len(e.get_text(" ", strip=True)))


def clean_author(text: Optional[str]) -> Optional[str]:
    """Strip profile clutter ("1,239 reviews", "4 followers", "Follow") from a name."""
    if not text:
        return None
    text = _AUTHOR_CLUTTER.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" -|,·•")
    text = re.sub(r"^(by|reviewed by|written by)\s+", "", text, flags=re.I).strip(" -|,·•")
    return text if 1 < len(text) <= 60 else None


def _pick_author(item: Tag) -> Optional[str]:
    """Prefer elements named *name*/author with short text over whole profile boxes."""
    best: Optional[Tuple[int, int, str]] = None
    for el in item.find_all(["span", "a", "div", "p", "strong", "b", "cite", "h5", "h6"]):
        attrs = _attrs_text(el)
        if el is item or not _AUTHOR_HINT.search(attrs):
            continue
        name = clean_author(el.get_text(" ", strip=True))
        if not name:
            continue
        rank = 0 if re.search(r"name|author", attrs, re.I) else 1
        cand = (rank, len(name), name)
        if best is None or cand < best:
            best = cand
    return best[2] if best else None


def _item_fields(item: Tag, page_url: str) -> Optional[Dict[str, Any]]:
    text_el = _pick_text_el(item)
    title_el = _find_hinted(item, _TITLE_HINT, ["h2", "h3", "h4", "h5", "a", "span", "div", "strong"]) or item.find(["h3", "h4", "h5"])
    author = _pick_author(item)
    time_el = item.find("time")
    date_val = (time_el.get("datetime") or time_el.get_text(" ", strip=True)) if time_el else None
    if not date_val:
        date_el = _find_hinted(item, _DATE_HINT, ["span", "div", "p", "small"])
        date_val = date_el.get_text(" ", strip=True) if date_el else None
    if not date_val:
        # Short text that looks like a date ("April 3, 2016", "3 Mar 2026", "2 days ago")
        for el in item.find_all(["span", "a", "div", "p", "small", "time"]):
            txt = el.get_text(" ", strip=True)
            if 4 <= len(txt) <= 40 and _DATE_TEXT.search(txt):
                date_val = _DATE_TEXT.search(txt).group(0)
                break

    if text_el is not None and len(_clean(text_el.get_text(" ", strip=True))) >= MIN_TEXT:
        text = text_el.get_text(" ", strip=True)
    else:
        # Fall back to the whole block minus the small parts we already identified
        clone = BeautifulSoup(str(item), "html.parser")
        for el in clone.find_all(["script", "style", "button", "svg", "time"]):
            el.decompose()
        text = clone.get_text(" ", strip=True)
        if title_el is not None:
            text = text.replace(title_el.get_text(" ", strip=True), " ", 1)
        if author:
            text = text.replace(author, " ", 1)
        if date_val:
            text = text.replace(date_val, " ", 1)
    text = _clean(text)
    if len(text) < MIN_TEXT or _UI_MESSAGE_TEXT.search(text):
        return None
    if len(text) < 300 and _AGGREGATE_TEXT.search(text):
        return None  # a rating summary line, not a review

    rating, raw, best = extract_rating_from(item)
    link = item.find("a", href=re.compile(r"review|comment|#", re.I))
    title = title_el.get_text(" ", strip=True) if title_el is not None else None
    if title and (len(title) > 200 or title == text or (author and clean_author(title) == author)):
        title = None
    return _review(
        text, title=title, rating=rating, rating_raw=raw, best=best, author=author, date=date_val,
        review_id=item.get("id") or item.get("data-review-id") or item.get("data-id"),
        url=urljoin(page_url, link["href"]) if link and link.get("href") else None,
        method="heuristic",
    )


def extract_heuristic(soup: BeautifulSoup, page_url: str) -> List[Dict[str, Any]]:
    groups: Dict[Tuple[str, str], List[Tag]] = defaultdict(list)
    for el in _candidates(soup):
        groups[_signature(el)].append(el)

    best_items: List[Dict[str, Any]] = []
    best_score = 0.0
    for sig, els in groups.items():
        # keep only the outermost element when a group nests inside itself
        els = [e for e in els if not any(o is not e and o in e.parents for o in els)]
        if len(els) < 2:
            continue
        items = [f for f in (_item_fields(e, page_url) for e in els) if f]
        if len(items) < 2:
            continue
        lengths = [len(i["text"]) for i in items]
        med = median(lengths)
        if med < 25 or med > 4000:
            continue
        if len({i["text"] for i in items}) < max(2, len(items) // 2):
            continue  # same text repeated: boilerplate, not reviews
        fields = sum(bool(i["rating"]) + bool(i["author"]) + bool(i["date"]) + bool(i["title"]) for i in items) / len(items)
        score = len(items) * min(med, 600) * (1 + 0.25 * fields)
        if "review" in sig[1].lower():
            score *= 1.3
        if score > best_score:
            best_items, best_score = items, score
    return best_items


# ── page-level helpers ──────────────────────────────────────────────────

def find_next_page(soup: BeautifulSoup, page_url: str) -> Optional[str]:
    """Find a same-site 'next page' link."""
    host = urlsplit(page_url).netloc
    cands: List[str] = []
    for el in soup.find_all(["link", "a"], rel=True):
        if "next" in [r.lower() for r in (el.get("rel") or [])] and el.get("href"):
            cands.append(el["href"])
    for a in soup.find_all("a", href=True):
        label = " ".join(filter(None, [a.get_text(" ", strip=True), a.get("aria-label"), a.get("title")])).strip().lower()
        if re.fullmatch(r"(next|next page|next ›|next »|›|»|older|more reviews|older reviews|load more)", label) or \
                re.search(r"\bnext\b", str(a.get("aria-label") or "").lower()):
            cands.append(a["href"])
    for href in cands:
        if href.startswith(("javascript:", "#")):
            continue
        full = urljoin(page_url, href)
        if urlsplit(full).netloc == host and full.split("#")[0] != page_url.split("#")[0]:
            return full
    return None


_AGG_TEXT = re.compile(r"(\d(?:[.,]\d)?)\s*out of\s*5\s*stars?", re.I)
_AGG_COUNT = re.compile(r"\(\s*([\d,]+)\s*\)|([\d,]+)\s+(?:global\s+)?(?:ratings?|reviews?)\b", re.I)


def page_rating_summary(soup: BeautifulSoup) -> Optional[Tuple[float, Optional[int]]]:
    """The page's overall rating, e.g. (4.0, 79), from JSON-LD aggregateRating or "4.0 out of 5 stars (79)" text."""
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        try:
            data = json.loads((script.string or script.get_text() or "").strip())
        except (ValueError, TypeError):
            continue
        for obj in _walk(data):
            agg = obj.get("aggregateRating") if isinstance(obj, dict) else None
            if isinstance(agg, dict) and agg.get("ratingValue") is not None:
                value = normalize_rating(agg.get("ratingValue"), agg.get("bestRating"))
                count = agg.get("ratingCount") or agg.get("reviewCount")
                if value:
                    try:
                        return value, int(str(count).replace(",", "")) if count is not None else None
                    except ValueError:
                        return value, None
    for el in soup.find_all(string=_AGG_TEXT):
        if el.parent is None or _is_hidden(el.parent):
            continue
        value = normalize_rating(_AGG_TEXT.search(str(el)).group(1), 5)
        if not value:
            continue
        # The count is often in a sibling element: "4.0 out of 5 stars" ... "(79)"
        for scope in (el.parent, el.parent.parent):
            if scope is None:
                continue
            text = scope.get_text(" ", strip=True)
            if len(text) > 200:
                break
            m = _AGG_COUNT.search(_AGG_TEXT.sub(" ", text))
            if m:
                return value, int((m.group(1) or m.group(2)).replace(",", ""))
        return value, None
    return None


def page_subject(soup: BeautifulSoup) -> Optional[str]:
    """Best guess at what the page is about (product/business), for the company field."""
    og = soup.find("meta", attrs={"property": "og:title"}) or soup.find("meta", attrs={"name": "og:title"})
    if og and og.get("content"):
        return _clean(og["content"])[:120]
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return _clean(h1.get_text(" ", strip=True))[:120]
    if soup.title and soup.title.string:
        return _clean(soup.title.string)[:120]
    return None


# ── 4. Repeated blocks inside a reviews section (for sites with scrambled class names) ──

_INLINE_TAGS = {"span", "a", "b", "i", "em", "strong", "br", "u", "small", "sup", "sub", "q", "mark", "abbr", "code"}
_UI_NOISE = re.compile(
    r"was this review helpful\??|helpful\??\s*(yes|no)|\byes\s+no\s+funny\b|\baward\b|\breport( abuse)?\b|"
    r"\b(read|show|see) (more|less)\b|\breply\b|\bshare\b|\bflag\b",
    re.I,
)
_SPECS_TEXT = re.compile(r"\bpc specs\b|\b(v?ram|gpu|cpu|processor|graphics)\b[^.]{0,80}?\b\d+\s?(gb|mb|ghz)\b", re.I)
_PROFILE_HREF = re.compile(r"/(profiles?|user|users|member|members|people|id|author|reviewer)s?/", re.I)


def _shape(el: Tag) -> Tuple[str, str, str]:
    first = el.find(True)
    return (el.name, " ".join(el.get("class") or []),
            f"{first.name}.{' '.join(first.get('class') or [])}" if first is not None else "")


def _in_review_section(el: Tag) -> bool:
    for anc in list(el.parents)[:14]:
        if anc.name in ("body", "html", "[document]"):
            break
        if _REVIEW_WORD.search(_attrs_text(anc)):
            return True
        heading = anc.find_previous_sibling(["h1", "h2", "h3", "h4"])
        if heading is not None and re.search(r"reviews?|ratings?", heading.get_text(" ", strip=True), re.I):
            return True
    return False


def _text_block(item: Tag) -> Optional[Tag]:
    """Longest element whose children are all inline (a paragraph of prose)."""
    best, best_len = None, 0
    for el in [item] + item.find_all(True):
        if el.name in ("script", "style", "svg", "button"):
            continue
        if any(c.name not in _INLINE_TAGS for c in el.find_all(True, recursive=False)):
            continue
        t = el.get_text(" ", strip=True)
        if _SPECS_TEXT.search(t):
            continue  # "Reviewer's PC Specs: ... RAM: 16 GB" style boxes
        # Prefer prose: blocks with sentence punctuation count fully, others less
        n = len(t) * (1.0 if re.search(r"[.!?]", t) else 0.4)
        if n > best_len:
            best, best_len = el, n
    return best


def _recommended(item: Tag) -> Optional[bool]:
    for el in item.find_all(True):
        t = el.get_text(" ", strip=True)
        if t and len(t) <= 30:
            if re.fullmatch(r"not recommended", t, re.I):
                return False
            if re.fullmatch(r"recommended", t, re.I):
                return True
    return None


def _repeated_item(item: Tag, page_url: str) -> Optional[Dict[str, Any]]:
    block = _text_block(item)
    if block is None:
        return None
    text = _clean(_UI_NOISE.sub(" ", block.get_text(" ", strip=True)))
    if len(text) < 30 or _UI_MESSAGE_TEXT.search(text) or (len(text) < 300 and _AGGREGATE_TEXT.search(text)):
        return None
    if re.fullmatch(r"https?://\S+", text):
        return None  # just a link, no review text
    author = _pick_author(item)
    if not author:
        for a in item.find_all("a", href=True):
            if _PROFILE_HREF.search(a["href"]):
                author = clean_author(a.get_text(" ", strip=True))
                if author:
                    break
    date_val = None
    time_el = item.find("time")
    if time_el is not None:
        date_val = time_el.get("datetime") or time_el.get_text(" ", strip=True)
    if not date_val:
        for el in item.find_all(True):
            t = el.get_text(" ", strip=True)
            m = _DATE_TEXT.search(t) if 4 <= len(t) <= 60 else None
            if m:
                date_val = m.group(0)
                break
    rating, raw, best = extract_rating_from(item)
    return _review(text, rating=rating, rating_raw=raw, best=best, author=author, date=date_val,
                   review_id=item.get("id") or item.get("data-review-id"), method="repeated_blocks",
                   recommended=_recommended(item))


def extract_repeated(soup: BeautifulSoup, page_url: str) -> List[Dict[str, Any]]:
    """Find containers whose children repeat with the same shape and read like reviews.

    A page can have several such lists (e.g. "Most helpful" and "Recently
    posted"), so every qualifying list is used; duplicate texts are dropped.
    """
    found: List[Dict[str, Any]] = []
    seen_texts: set = set()
    for container in soup.find_all(True):
        kids = container.find_all(True, recursive=False)
        if len(kids) < 3 or container.name in ("nav", "select", "head", "table", "tbody", "thead"):
            continue
        groups: Dict[Tuple[str, str, str], List[Tag]] = defaultdict(list)
        for k in kids:
            groups[_shape(k)].append(k)
        for els in groups.values():
            if len(els) < 3 or not _in_review_section(els[0]) or _is_hidden(els[0]):
                continue
            items = [f for f in (_repeated_item(e, page_url) for e in els) if f]
            if len(items) < 3 or len({i["text"] for i in items}) < len(items) * 0.8:
                continue
            words = median(len(i["text"].split()) for i in items)
            prose = sum(1 for i in items if re.search(r"[.!?]", i["text"])) / len(items)
            if words < 8 or prose < 0.5:
                continue  # menus, tag lists, category grids
            with_meta = sum(
                1 for i in items if i["author"] or i["date"] or i["rating"] or i["recommended"] is not None
            )
            if with_meta < len(items) / 2:
                continue  # help texts / filter options: real review cards carry an author, date or verdict
            for item in items:
                key = item["text"].lower()
                if key not in seen_texts:
                    seen_texts.add(key)
                    found.append(item)
    return found


def extract_reviews(html: str, page_url: str) -> Tuple[List[Dict[str, Any]], Optional[str], BeautifulSoup]:
    """Run the strategies in order. Returns (reviews, item_name, soup)."""
    soup = BeautifulSoup(html, "html.parser")
    reviews, item_name = extract_json_ld(soup, page_url)
    if not reviews:
        reviews = extract_microdata(soup, page_url)
    if not reviews:
        reviews = extract_heuristic(soup, page_url)
    if not reviews:
        reviews = extract_repeated(soup, page_url)
    return reviews, item_name, soup
