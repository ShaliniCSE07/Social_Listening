from enum import Enum


class Platform(str, Enum):
    twitter_x = "twitter_x"
    instagram = "instagram"
    linkedin = "linkedin"
    reddit = "reddit"
    google = "google"
    facebook = "facebook"
    news_blog = "news_blog"
    other = "other"


class Method(str, Enum):
    api = "api"
    dataset = "dataset"
    scraping = "scraping"


class ContentType(str, Enum):
    post = "post"
    comment = "comment"
    reply = "reply"
    review = "review"
    article = "article"


class AttemptStatus(str, Enum):
    success = "success"
    failed = "failed"
    rate_limited = "rate_limited"
    empty = "empty"
    skipped = "skipped"
    budget_exhausted = "budget_exhausted"

