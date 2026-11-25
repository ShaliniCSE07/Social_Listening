"""Tests for the stand-alone review scraper (no network: pages are served by a fake fetcher)."""
import json

import pytest
from fastapi.testclient import TestClient

from src.contracts.enums import ContentType, Method, Platform
from src.contracts.io import read_mentions_jsonl
from src.review_scraper.engine import platform_for, scrape_reviews
from src.review_scraper.extractors import extract_reviews, normalize_rating
from src.review_scraper.fetcher import Fetcher, FetchError, validate_url


class FakeFetcher(Fetcher):
    """Serves canned HTML by URL; unknown URLs raise like a 404."""

    def __init__(self, pages):
        super().__init__(respect_robots=False)
        self.pages = pages
        self.requested = []

    def fetch(self, url):
        self.requested.append(url)
        if url not in self.pages:
            raise FetchError("The website returned HTTP 404.")
        return url, self.pages[url]


JSON_LD_PAGE = """
<html><head><title>Cafe Blue</title>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Restaurant","name":"Cafe Blue",
 "review":[
  {"@type":"Review","author":{"@type":"Person","name":"Asha"},"datePublished":"2026-05-01",
   "reviewBody":"Lovely coffee and very friendly staff, will come again.",
   "name":"Great coffee","reviewRating":{"@type":"Rating","ratingValue":"5","bestRating":"5"}},
  {"@type":"Review","author":"Ravi","datePublished":"2026-05-03",
   "reviewBody":"Food was cold and service slow on a quiet weekday.",
   "reviewRating":{"@type":"Rating","ratingValue":4,"bestRating":10}}
 ],
 "aggregateRating":{"@type":"AggregateRating","ratingValue":"4.2","reviewCount":"2"}}
</script></head><body><h1>Cafe Blue</h1></body></html>
"""

MICRODATA_PAGE = """
<html><body><h1>Super Phone X</h1>
<div itemscope itemtype="https://schema.org/Review">
  <span itemprop="name">Battery is great</span>
  <span itemprop="author" itemscope itemtype="https://schema.org/Person"><span itemprop="name">Meera</span></span>
  <meta itemprop="datePublished" content="2026-01-10">
  <div itemprop="reviewRating" itemscope itemtype="https://schema.org/Rating">
    <meta itemprop="ratingValue" content="4"><meta itemprop="bestRating" content="5"></div>
  <p itemprop="reviewBody">Battery easily lasts two days, camera is average though.</p>
</div>
<div itemscope itemtype="https://schema.org/Review">
  <span itemprop="author">Karan</span>
  <div itemprop="reviewRating" itemscope itemtype="https://schema.org/Rating"><span itemprop="ratingValue">2</span></div>
  <p itemprop="reviewBody">Screen cracked within a week of normal use, disappointed.</p>
</div>
</body></html>
"""

HEURISTIC_PAGE = """
<html><body><h1>Hotel Sunrise reviews</h1>
<div class="reviews-summary">4.1 average from 120 reviews</div>
<ul class="review-list">
  <li class="review-item" id="r1">
    <span class="review-author">Priya S.</span><time datetime="2026-03-02">2 Mar 2026</time>
    <div class="star-rating" aria-label="Rated 4 out of 5 stars"></div>
    <h4 class="review-title">Clean rooms</h4>
    <p class="review-text">Rooms were spotless and the breakfast buffet had good variety.</p>
  </li>
  <li class="review-item" id="r2">
    <span class="review-author">John D.</span><span class="review-date">5 Mar 2026</span>
    <div class="stars"><i class="star full"></i><i class="star full"></i><i class="star"></i><i class="star"></i><i class="star"></i></div>
    <p class="review-text">Noisy at night because of the road, staff were helpful though.</p>
  </li>
  <li class="review-item" id="r3">
    <span class="review-author">Ana</span>
    <span class="rating rating-5"></span>
    <p class="review-text">Best stay of our trip, the rooftop view is incredible!</p>
  </li>
</ul>
<a class="next" rel="next" href="/hotel?page=2">Next</a>
</body></html>
"""

HEURISTIC_PAGE_2 = """
<html><body><ul class="review-list">
  <li class="review-item"><span class="review-author">Zoe</span><span class="rating">★★★☆☆</span>
    <p class="review-text">Average experience overall, wifi kept dropping in the room.</p></li>
  <li class="review-item"><span class="review-author">Priya S.</span>
    <p class="review-text">Rooms were spotless and the breakfast buffet had good variety.</p></li>
</ul></body></html>
"""

NO_REVIEWS_PAGE = "<html><body><h1>About us</h1><p>We are a company that does things.</p></body></html>"


# ── extraction strategies ────────────────────────────────────────────────

def test_json_ld_reviews_and_rating_scaling():
    reviews, item, _ = extract_reviews(JSON_LD_PAGE, "https://cafe.example/")
    assert item == "Cafe Blue"
    assert [r["extraction_method"] for r in reviews] == ["json_ld", "json_ld"]
    assert reviews[0]["author"] == "Asha" and reviews[0]["rating"] == 5.0 and reviews[0]["title"] == "Great coffee"
    assert reviews[1]["author"] == "Ravi" and reviews[1]["rating"] == 2.0  # 4 out of 10


def test_microdata_reviews():
    reviews, _, _ = extract_reviews(MICRODATA_PAGE, "https://shop.example/phone")
    assert len(reviews) == 2 and all(r["extraction_method"] == "microdata" for r in reviews)
    assert reviews[0]["author"] == "Meera" and reviews[0]["rating"] == 4.0 and reviews[0]["date"] == "2026-01-10"
    assert reviews[1]["author"] == "Karan" and reviews[1]["rating"] == 2.0


def test_heuristic_reviews_with_different_star_styles():
    reviews, _, _ = extract_reviews(HEURISTIC_PAGE, "https://hotel.example/hotel")
    assert len(reviews) == 3 and all(r["extraction_method"] == "heuristic" for r in reviews)
    by_author = {r["author"]: r for r in reviews}
    assert by_author["Priya S."]["rating"] == 4.0          # aria-label
    assert by_author["Priya S."]["date"] == "2026-03-02"   # <time datetime>
    assert by_author["Priya S."]["title"] == "Clean rooms"
    assert by_author["John D."]["rating"] == 2.0           # filled star icons
    assert by_author["Ana"]["rating"] == 5.0               # class rating-5
    assert "average from 120" not in " ".join(r["text"] for r in reviews)  # summary box ignored


@pytest.mark.parametrize("value,best,expected", [(4, 5, 4.0), (8, 10, 4.0), ("4,5", None, 4.5), (0, 5, None), (90, None, 4.5)])
def test_normalize_rating(value, best, expected):
    assert normalize_rating(value, best) == expected


# ── engine ───────────────────────────────────────────────────────────────

def test_engine_follows_next_page_dedupes_and_builds_mentions():
    fetcher = FakeFetcher({
        "https://hotel.example/hotel": HEURISTIC_PAGE,
        "https://hotel.example/hotel?page=2": HEURISTIC_PAGE_2,
    })
    res = scrape_reviews("https://hotel.example/hotel", max_pages=3, fetcher=fetcher, delay_seconds=0, mode="static", run_id="scrape_x")

    assert res.error is None and res.pages_fetched == 2
    assert len(res.mentions) == 4  # 3 + 1 new (duplicate Priya review dropped)
    assert res.company == "Hotel Sunrise reviews"  # from <h1> when no company given
    m = res.mentions[0]
    assert m.method_used == Method.scraping and m.content_type_hint == ContentType.review
    assert m.platform == Platform.other and m.source == "hotel.example" and m.run_id == "scrape_x"
    assert m.raw_payload["rating"] == 4.0 and m.raw_payload["page_url"] == "https://hotel.example/hotel"
    zoe = next(x for x in res.mentions if x.raw_payload["author"] == "Zoe")
    assert zoe.raw_payload["rating"] == 3.0  # ★★★☆☆


def test_engine_respects_page_and_review_limits():
    fetcher = FakeFetcher({"https://hotel.example/hotel": HEURISTIC_PAGE, "https://hotel.example/hotel?page=2": HEURISTIC_PAGE_2})
    res = scrape_reviews("https://hotel.example/hotel", max_pages=1, fetcher=fetcher, delay_seconds=0, mode="static")
    assert res.pages_fetched == 1 and len(fetcher.requested) == 1

    res = scrape_reviews("https://hotel.example/hotel", max_reviews=2, fetcher=fetcher, delay_seconds=0, mode="static")
    assert len(res.mentions) == 2 and any("limit of 2" in w for w in res.warnings)


def test_engine_reports_no_reviews_and_fetch_errors():
    res = scrape_reviews("https://x.example/about", fetcher=FakeFetcher({"https://x.example/about": NO_REVIEWS_PAGE}), delay_seconds=0, mode="static")
    assert res.mentions == [] and res.error is None and "No reviews were found" in res.warnings[0]

    res = scrape_reviews("https://x.example/missing", fetcher=FakeFetcher({}), delay_seconds=0, mode="static")
    assert res.error == "The website returned HTTP 404."


def test_company_override_and_platform_from_domain():
    url = "https://www.tripadvisor.com/Restaurant_Review-x.html"
    res = scrape_reviews(url, company="Cafe Blue Pune", fetcher=FakeFetcher({url: JSON_LD_PAGE}), delay_seconds=0, mode="static")
    assert res.company == "Cafe Blue Pune" and res.mentions[0].platform == Platform.tripadvisor
    assert platform_for("maps.google.com") == Platform.google
    assert platform_for("x.com") == Platform.twitter_x and platform_for("example.com") == Platform.other


# ── URL safety ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", ["ftp://example.com/x", "http://127.0.0.1/admin", "http://localhost:8000/",
                                 "http://10.0.0.5/", "http://169.254.169.254/latest", "https://user:pw@example.com/", "not a url"])
def test_unsafe_or_invalid_urls_are_refused(url):
    with pytest.raises(FetchError):
        validate_url(url)


# ── API ──────────────────────────────────────────────────────────────────

def test_api_scrape_list_get_and_download(monkeypatch, tmp_path):
    from src.service import main
    from src.service.routes import review_scraper as routes

    monkeypatch.setattr(routes, "SCRAPES_DIR", tmp_path / "scrapes")
    pages = {"https://cafe.example/": JSON_LD_PAGE}
    real = routes.scrape_reviews
    monkeypatch.setattr(routes, "scrape_reviews",
                        lambda url, **kw: real(url, fetcher=FakeFetcher(pages), delay_seconds=0, **kw))
    client = TestClient(main.app)

    body = client.post("/api/review-scraper", json={"url": "https://cafe.example/", "max_pages": 1}).json()
    assert body["status"] == "completed" and body["reviews_count"] == 2
    assert body["company"] == "Cafe Blue" and body["methods"] == {"json_ld": 2}
    assert body["reviews"][0]["rating"] == 5.0
    job_id = body["job_id"]

    # Output is only mentions.jsonl (+ job.json summary), no attempts.jsonl
    files = sorted(p.name for p in (tmp_path / "scrapes" / job_id).iterdir())
    assert files == ["job.json", "mentions.jsonl"]

    dl = client.get(body["download_url"])
    assert dl.status_code == 200
    lines = [json.loads(l) for l in dl.text.splitlines() if l.strip()]
    assert len(lines) == 2 and lines[0]["method_used"] == "scraping" and lines[0]["run_id"] == job_id
    # File validates against the collection contract
    grouped = read_mentions_jsonl(tmp_path / "scrapes" / job_id / "mentions.jsonl")
    assert sum(len(v) for v in grouped.values()) == 2

    assert client.get("/api/review-scraper").json()[0]["job_id"] == job_id
    assert client.get(f"/api/review-scraper/{job_id}").json()["reviews_count"] == 2
    assert client.get("/api/review-scraper/../../etc/download").status_code == 404
    assert client.get("/api/review-scraper/scrape_zzzz/download").status_code == 404


def test_api_failed_scrape_is_saved_with_error(monkeypatch, tmp_path):
    from src.service import main
    from src.service.routes import review_scraper as routes

    monkeypatch.setattr(routes, "SCRAPES_DIR", tmp_path / "scrapes")
    client = TestClient(main.app)
    body = client.post("/api/review-scraper", json={"url": "http://127.0.0.1/secret"}).json()
    assert body["status"] == "failed" and "not allowed" in body["error"] and body["reviews_count"] == 0


# ── regressions from real-site layouts (synthetic pages with the same structure) ──

PROFILE_CARD_PAGE = """
<html><body><h1>A Book</h1>
""" + "".join(f"""
<article class="ReviewCard">
  <div class="ReviewCard__profile"><div class="ReviewerProfile ReviewerProfile--medium">
    <section class="ReviewerProfile__info">
      <div class="ReviewerProfile__name"><a href="/user/{i}">Reader {i}</a></div>
      <div class="ReviewerProfile__meta"><span>1,2{i}9 reviews</span><span>4 followers</span></div>
    </section>
    <div class="ReviewerProfile__follow"><button>Follow</button> Follow</div>
  </div></div>
  <section class="ReviewCard__content">
    <section class="ReviewCard__row"><span class="RatingStars" aria-label="Rating {i} out of 5"></span>
      <span class="Text"><a href="/review/{i}">April {i}, 2016</a></span></section>
    <section class="ReviewText"><section class="ReviewText__content"><span class="Formatted">
      Review number {i}: a moving story that I keep coming back to every few years.</span></section></section>
    <section class="ReviewCard__tags">classics favorites ...more</section>
  </section>
</article>""" for i in range(1, 4)) + "</body></html>"

FORM_MESSAGES_PAGE = """
<html><body><h1>Company page</h1>
<form class="review-form">
  <textarea class="comment-box"></textarea>
  <label class="invalid-feedback">Please enter your full name.</label>
  <label class="invalid-feedback">Please enter a valid email address.</label>
  <div class="invalid-feedback">Please check the attached files.</div>
</form>
<div class="invalid-feedback">Please enter your review title.</div>
<div class="invalid-feedback">Please enter your review text here.</div>
</body></html>
"""

SUMMARY_ONLY_PAGE = """
<html><body><h1>Some Game</h1>
<div class="user_reviews">
  <a class="user_reviews_summary_row">Recent Reviews: <span class="responsive_reviewdesc_short">Overwhelmingly Positive (98% of 1,519)</span>
    <span class="responsive_reviewdesc">- 98% of the 1,519 user reviews in the last 30 days are positive.</span></a>
  <a class="user_reviews_summary_row">All Reviews: <span class="responsive_reviewdesc_short">Very Positive (95% of 175,174)</span>
    <span class="responsive_reviewdesc">- 95% of the 175,174 user reviews for this game are positive.</span></a>
</div>
<div class="review_ctn"></div>
</body></html>
"""


def test_profile_cards_give_clean_author_text_and_date():
    reviews, _, _ = extract_reviews(PROFILE_CARD_PAGE, "https://books.example/b/1")
    assert len(reviews) == 3
    r = reviews[0]
    assert r["author"] == "Reader 1"                 # not "Reader 1 1,219 reviews 4 followers Follow"
    assert r["text"].startswith("Review number 1:")  # not prefixed with profile/date text
    assert "followers" not in r["text"] and "...more" not in r["text"]
    assert r["rating"] == 1.0 and r["date"] == "April 1, 2016"
    assert r["title"] is None                        # author name is not reused as a title


def test_form_validation_messages_are_not_reviews():
    reviews, _, _ = extract_reviews(FORM_MESSAGES_PAGE, "https://company.example/")
    assert reviews == []


def test_rating_summary_rows_are_not_reviews():
    reviews, _, _ = extract_reviews(SUMMARY_ONLY_PAGE, "https://games.example/app/1")
    assert reviews == []


@pytest.mark.parametrize("raw,expected", [
    ("Brina 1,239 reviews 4 followers Follow Follow", "Brina"),
    ("By John D.", "John D."),
    ("Verified Buyer", None),
    ("", None),
])
def test_clean_author(raw, expected):
    from src.review_scraper.extractors import clean_author
    assert clean_author(raw) == expected


# ── review lists with scrambled class names (Steam-style) ──

def _scrambled_card(author, verdict, posted, body, specs=False):
    spec = "<div class='q1-'>Reviewer's PC Specs: Windows 10 AMD Ryzen 7 Processor - RAM: 16 GB</div>" if specs else ""
    return f"""<div><div class='Ab3x-'><div class='Kq9z-'><a href='https://community.example/profiles/{author}'>{author}</a>
      <div class='Zz1-'>{verdict}</div><div class='Yy2-'>12.5 hrs on record</div><div class='Ww3-'>Posted: {posted}</div></div>
      <div class='Bd7k-'>{body}</div>{spec}<div class='Hp0-'>Was this review helpful? <button>Yes</button><button>No</button> Funny Award</div>
    </div></div>"""


SCRAMBLED_PAGE = """<html><body><h1>Space Game on Store</h1>
<div class="review_ctn"><h2>Customer reviews for Space Game</h2>
  <div class="Fp1-"><div class="Fp2-">Use new helpfulness system. Only applies to Summary and Most Helpful views.</div>
    <div class="Fp2-">Filter reviews by the user's playtime when the review was written, in hours.</div>
    <div class="Fp2-">Exclude reviews written in a specific date range, select on the graph above please.</div></div>
  <div class="qbN-">""" + "".join([
    _scrambled_card("Nova", "Recommended", "31 October", "Brilliant puzzles and a funny story. Co-op is the best part of it."),
    _scrambled_card("Orbit", "Not Recommended", "5 November", "Crashed twice on my laptop and the controls felt clumsy to me."),
    _scrambled_card("Comet", "Recommended", "7 November", "Short but sweet. Worth it on sale, I would play it again for sure.", specs=True),
    _scrambled_card("LinkGuy", "Recommended", "9 November", "https://community.example/sharedfiles/123"),
]) + """</div></div>
<div class="Cat-"><div class="Cat1-">Action Adventure Racing Sports Strategy</div><div class="Cat1-">Puzzle Indie Casual Simulation RPG</div>
  <div class="Cat1-">Horror Shooter Fighting Platformer Music</div></div>
</body></html>"""


def test_scrambled_class_review_list():
    reviews, _, _ = extract_reviews(SCRAMBLED_PAGE, "https://store.example/app/1")
    assert [r["author"] for r in reviews] == ["Nova", "Orbit", "Comet"]  # link-only review and filter help texts dropped
    assert all(r["extraction_method"] == "repeated_blocks" for r in reviews)
    by = {r["author"]: r for r in reviews}
    assert by["Nova"]["recommended"] is True and by["Orbit"]["recommended"] is False
    assert by["Nova"]["date"] == "31 October"
    assert by["Comet"]["text"].startswith("Short but sweet")  # not the PC specs box
    assert "helpful" not in " ".join(r["text"].lower() for r in reviews)


def test_repeated_blocks_need_a_reviews_section():
    page = SCRAMBLED_PAGE.replace('class="review_ctn"', 'class="Main-"').replace("Customer reviews for", "About")
    reviews, _, _ = extract_reviews(page, "https://store.example/app/1")
    assert reviews == []


def test_recommended_reaches_mentions():
    from src.review_scraper.engine import scrape_reviews as sr
    url = "https://store.example/app/1"
    res = sr(url, fetcher=FakeFetcher({url: SCRAMBLED_PAGE}), delay_seconds=0, mode="static")
    assert [m.raw_payload["recommended"] for m in res.mentions] == [True, False, True]


# ── hidden pop-up forms and pages that show only an overall rating (Amazon-style) ──

HIDDEN_FEEDBACK_FORM_PAGE = """<html><body><h1>Cotton Kurti</h1>
<div id="averageCustomerReviews"><span>4.0</span> <span class="a-icon-alt">4.0 out of 5 stars</span> <span>(79)</span></div>
<div id="customerReviews"></div>
<div class="a-popover-preload" id="a-popover-pricingFeedback-modal-content"><div id="feedbackForm" style="display: none;">
  <div class="priceavailability"><fieldset><fieldset>
    <div class="grid-container" id="pricingFeedback_onlineInput"><div class="grid-row">
      <label class="grid-label">URL * : Price incl. VAT * : Shipping cost : Date of the price (MM/DD/YYYY): 01 02 03 04 05 06 07 08 09 10 11 12</label></div></div>
  </fieldset></fieldset>
  <div class="review-feedback-row"><div class="review-feedback-text">Enter the store name where you found this product, please tell us.</div></div>
  <div class="review-feedback-row"><div class="review-feedback-text">Enter the price you saw at that store and the date you saw it.</div></div>
  </div></div></div>
<div hidden><div class="review-item"><p class="review-text">Hidden template review text that must not be scraped at all.</p></div>
  <div class="review-item"><p class="review-text">Another hidden template review that must not be scraped either.</p></div></div>
</body></html>"""


def test_hidden_popups_and_forms_are_ignored():
    reviews, _, _ = extract_reviews(HIDDEN_FEEDBACK_FORM_PAGE, "https://shop.example/dp/1")
    assert reviews == []


def test_overall_rating_reported_when_reviews_are_missing():
    url = "https://shop.example/dp/1"
    res = scrape_reviews(url, fetcher=FakeFetcher({url: HIDDEN_FEEDBACK_FORM_PAGE}), delay_seconds=0, mode="static")
    assert res.mentions == [] and res.page_rating == (4.0, 79)
    assert res.warnings[0].startswith("This page shows an overall rating of 4.0/5 from 79 ratings")


def test_overall_rating_from_json_ld():
    from bs4 import BeautifulSoup
    from src.review_scraper.extractors import page_rating_summary
    html = """<script type="application/ld+json">{"@type":"Product","name":"X",
      "aggregateRating":{"@type":"AggregateRating","ratingValue":"8.6","bestRating":"10","ratingCount":"1,234"}}</script>"""
    assert page_rating_summary(BeautifulSoup(html, "html.parser")) == (4.3, 1234)
