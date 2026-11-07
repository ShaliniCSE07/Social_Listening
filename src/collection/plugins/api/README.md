# API Collection Plugin

## Purpose
Collects mentions, reviews, and posts via official platform APIs, beginning with the official **Reddit API** (`RedditAPIConnector`).

## Reddit App Setup
1. Log in to [Reddit](https://www.reddit.com) and navigate to **Preferences > Apps** (or https://www.reddit.com/prefs/apps).
2. Click **Create another app...** (or **Create an app...**).
3. Select **script** as the application type.
4. Fill in name, description, and set redirect URI to `http://localhost:8080`.
5. Once created:
   - The string under the app title is your `REDDIT_CLIENT_ID`.
   - The `secret` field is your `REDDIT_CLIENT_SECRET`.
6. Define an identifying `REDDIT_USER_AGENT` following Reddit API guidelines (e.g., `SocialListeningBot/1.0 by YourUsername`).

## Environment Variables
Set the following variables in your `.env` file:
```bash
REDDIT_CLIENT_ID=your_client_id_here
REDDIT_CLIENT_SECRET=your_client_secret_here
REDDIT_USER_AGENT=SocialListeningBot/1.0 (+https://github.com/social-listening)
```

## Configuration & Limits
Configured in `config/plugins/api.yaml` under `reddit`:
- `max_items`: Maximum number of search results retrieved per run (default: `200`).
- `request_timeout`: HTTP request timeout in seconds (default: `15`).
- `max_retries`: Maximum retries for transient 5xx errors or timeouts (default: `2`).
- `token_url`: OAuth token endpoint (`https://www.reddit.com/api/v1/access_token`).
- `api_base_url`: API base endpoint (`https://oauth.reddit.com`).

Rate limiting:
- Rate limit responses (HTTP 429) set the attempt status to `rate_limited` and respect the `Retry-After` header without blocking endlessly.
- Authentication or permission errors (HTTP 401/403) immediately fail without retry.

## Running Tests
Run unit tests (mocked with `responses`):
```bash
python -m pytest tests/collection/api/test_reddit_api.py -v
```

Run live integration test (requires real credentials set in environment):
```bash
python -m pytest tests/collection/api/test_reddit_api.py -m live -v
```
