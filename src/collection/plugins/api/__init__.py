"""API collection plugin package."""
from src.collection.plugins.api.google_places import GooglePlacesConnector
from src.collection.plugins.api.reddit_api import RedditAPIConnector
from src.collection.plugins.api.tripadvisor_reviews import TripadvisorReviewsConnector

CONNECTORS = [RedditAPIConnector, GooglePlacesConnector, TripadvisorReviewsConnector]
