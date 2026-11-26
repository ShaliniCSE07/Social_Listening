"""Processor mapping of real collection payloads (datasets, Reddit, Google, Hacker News)."""
import os
from datetime import datetime, timezone

import pytest

os.environ.setdefault("SOCL_AUTHOR_PEPPER", "test-pepper")

import processor  # noqa: E402
from models import (  # noqa: E402
    AttemptStatus,
    CollectionAttempt,
    ContentTypeHint,
    Method,
    Platform,
    RawMention,
)

NOW = datetime(2026, 11, 17, 7, 0, tzinfo=timezone.utc)


def _raw(payload, company="Zomato", platform=Platform.OTHER, method=Method.DATASET, item_id=None, url=None,
         hint=ContentTypeHint.REVIEW):
    return RawMention(
        company=company,
        platform=platform,
        item_id=item_id,
        url=url,
        content_type_hint=hint,
        raw_payload=payload,
        source="test",
        method_used=method,
        tool_used="test",
        collected_at=NOW,
    )


# Kaggle app review row exactly as the dataset connector delivers it
KAGGLE_ROW = {
    "App": "Zomato",
    "review_description": "Great offers and fast delivery",
    "review_date": "2023-07-23 15:52:11",
    "rating": "5",
    "developer_response": "",
    "dataset_key": "kaggle_zomato_app_reviews",
    "dataset_match_basis": "company_column",
}


def test_empty_rating_is_missing_not_a_crash():
    mapped = processor._map_from_payload(_raw({**KAGGLE_ROW, "rating": ""}))
    assert mapped["rating"] is None


def test_string_numbers_are_converted():
    mapped = processor._map_from_payload(_raw(KAGGLE_ROW))
    assert mapped["rating"] == 5.0


def test_unreadable_numbers_become_none():
    mapped = processor._map_from_payload(_raw({"text": "Zomato", "rating": "n/a", "score": "", "num_comments": "x"}))
    assert mapped["rating"] is None
    assert mapped["reactions"]["likes"] is None
    assert mapped["reactions"]["comments"] is None


def test_dataset_text_and_date_come_from_catalogue_columns():
    mapped = processor._map_from_payload(_raw(KAGGLE_ROW))
    assert mapped["text"] == "Great offers and fast delivery"
    # timezone-less dataset dates are treated as UTC
    assert mapped["posted_at"] == datetime(2023, 7, 23, 15, 52, 11, tzinfo=timezone.utc)


def test_sample_dataset_review_text():
    payload = {"review_id": "R1", "review_text": "Easy app", "review_date": "2021-05-10T00:09:00Z",
               "rating": "4", "author": "user_1", "dataset_key": "sample_reviews_local",
               "dataset_match_basis": "company_column"}
    mapped = processor._map_from_payload(_raw(payload))
    assert mapped["text"] == "Easy app"
    assert mapped["author_handle"] == "user_1"
    assert mapped["posted_at"] == datetime(2021, 5, 10, 0, 9, tzinfo=timezone.utc)


def test_reddit_epoch_date_and_link_post_title():
    payload = {"title": "Zomato raises prices", "selftext": "", "author": "someone",
               "created_utc": 1700000000.0, "score": 12, "num_comments": 3}
    mapped = processor._map_from_payload(_raw(payload, platform=Platform.REDDIT, method=Method.API,
                                              hint=ContentTypeHint.POST))
    assert mapped["text"] == "Zomato raises prices"
    assert mapped["posted_at"] == datetime.fromtimestamp(1700000000, tz=timezone.utc)
    assert mapped["reactions"]["likes"] == 12
    assert mapped["reactions"]["comments"] == 3


def test_google_places_review_shape():
    payload = {"text": {"text": "Zomato office was friendly", "languageCode": "en"},
               "rating": 4, "publishTime": "2026-01-05T10:00:00Z",
               "authorAttribution": {"displayName": "A Person"}, "place_name": "Zomato HQ"}
    mapped = processor._map_from_payload(_raw(payload, platform=Platform.GOOGLE, method=Method.API))
    assert mapped["text"] == "Zomato office was friendly"
    assert mapped["author_handle"] == "A Person"
    assert mapped["rating"] == 4.0
    assert mapped["posted_at"] == datetime(2026, 1, 5, 10, tzinfo=timezone.utc)
    assert mapped["place"] == "Zomato HQ"


def test_tripadvisor_rapidapi_review_shape():
    payload = {"reviewId": "1085940974", "rating": 5, "title": "Great stay",
               "text": "The staff was welcoming and very helpful.",
               "publishedAt": "2026-11-18T17:53:01.925Z", "reviewerName": "Reviewer A",
               "language": "en", "placeName": "Hotel Edison Times Square",
               "source_match_basis": "place_page"}
    mapped = processor._map_from_payload(_raw(payload, platform=Platform.TRIPADVISOR, method=Method.API))
    assert mapped["text"] == "The staff was welcoming and very helpful."
    assert mapped["author_handle"] == "Reviewer A"
    assert mapped["rating"] == 5.0
    assert mapped["posted_at"] == datetime(2026, 11, 18, 17, 53, 1, 925000, tzinfo=timezone.utc)
    assert mapped["language"] == "en"


def test_hackernews_story_uses_title_and_comment_uses_text():
    story = {"item_id": "1", "title": "Amazon launches X", "text": None, "author": "pg", "points": 50,
             "comment_count": 10}
    comment = {"item_id": "2", "title": None, "text": "Amazon is fine", "author": "dang"}
    m1 = processor._map_from_payload(_raw(story, company="Amazon", platform=Platform.NEWS_BLOG,
                                          method=Method.SCRAPING, url=""))
    m2 = processor._map_from_payload(_raw(comment, company="Amazon", platform=Platform.NEWS_BLOG,
                                          method=Method.SCRAPING))
    assert m1["text"] == "Amazon launches X"
    assert m1["reactions"]["likes"] == 50 and m1["reactions"]["comments"] == 10
    assert m1["url"] is None  # "" from the scraper counts as missing
    assert m2["text"] == "Amazon is fine"


def test_original_reddit_rss_payload_maps_as_before():
    payload = {"id": "t1", "author": "jane_doe", "body": "Acme text", "updated": "2026-10-26T09:14:00Z"}
    mapped = processor._map_from_payload(_raw(payload, company="Acme", platform=Platform.REDDIT, method=Method.RSS))
    assert mapped["text"] == "Acme text"
    assert mapped["author_handle"] == "jane_doe"
    assert mapped["posted_at"] == datetime(2026, 10, 26, 9, 14, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "text,payload,expected",
    [
        ("Zomato is late again", {}, ("names company directly", "confirmed")),
        ("Eternal shares fell", {}, ("names company directly", "confirmed")),  # alt spelling
        ("ping @zomatocare please", {}, ("tags the account", "confirmed")),     # handle
        ("Great app", {"dataset_match_basis": "company_column"}, ("identified by source", "source")),
        ("Great app", {"dataset_match_basis": "default_company"}, ("identified by source", "source")),
        ("Great app", {"dataset_match_basis": "text_mention"}, (None, "")),
        ("Lovely staff", {"source_match_basis": "place_page"}, ("identified by source", "source")),
        ("Unrelated post", {}, (None, "")),
    ],
)
def test_company_match(text, payload, expected):
    assert processor._company_match("Zomato", text, payload) == expected


def test_process_mentions_keeps_dataset_reviews(monkeypatch):
    mongomock = pytest.importorskip("mongomock")
    db = mongomock.MongoClient()["socl_db"]
    db.records.create_index([("record_id", 1), ("version", 1)], unique=True)
    monkeypatch.setattr(processor, "get_db", lambda: db)
    monkeypatch.setattr(processor, "mask_text", lambda t: (t, True))

    rows = [
        {**KAGGLE_ROW, "review_description": "Great offers", "rating": ""},
        {**KAGGLE_ROW, "review_description": "Slow refunds", "rating": "2"},   # same date, no id
        {**KAGGLE_ROW, "review_description": "Great offers", "rating": ""},   # exact duplicate
    ]
    attempt = CollectionAttempt(company="Zomato", platform=Platform.OTHER, method=Method.DATASET,
                                status=AttemptStatus.SUCCESS, item_count=3, cost_usd=0.0,
                                started_at=NOW, finished_at=NOW)
    result = processor.process_mentions([_raw(r) for r in rows], [attempt], "run_t", {}, "full")

    assert result["inserted"] == 2
    assert result["counters"]["duplicates"] == 1
    assert result["counters"]["wrong_company"] == 0
    assert result["counters"]["quarantined"] == 0
    recs = {r.text: r for r in result["records"]}
    # rows without IDs but different text no longer share a mention ID
    assert recs["Great offers"].mention_id != recs["Slow refunds"].mention_id
    assert recs["Great offers"].rating is None
    assert recs["Slow refunds"].rating == 2.0
    assert recs["Great offers"].mention_type == "identified by source"
    assert recs["Great offers"].company_match == "source"
