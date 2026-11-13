"""Hacker News parser implementation.

The parser handles two page types:
- Listing page – extracts story entries.
- Item page – extracts the story and its comments.

Both return a list of dicts with a unified set of keys; missing keys are omitted.
"""

from bs4 import BeautifulSoup
from typing import List, Dict

from .base import Parser
from . import register


class HackerNewsParser(Parser):
    """Parse Hacker News HTML.

    The HTML structure is based on the real Hacker News pages but the tests use
    hand‑crafted fixtures that follow the same element classes.
    """

    def _parse_listing(self, soup: BeautifulSoup, page_url: str) -> List[Dict]:
        items: List[Dict] = []
        # Each story is represented by a pair of rows: the first with class 'athing',
        # the second with class 'subtext'.
        for story in soup.select('tr.athing'):
            story_id = story.get('id')
            title_tag = story.select_one('a.storylink')
            title = title_tag.get_text(strip=True) if title_tag else ''
            link = title_tag['href'] if title_tag and title_tag.has_attr('href') else ''
            # Subtext row follows the story row
            subtext = story.find_next_sibling('tr').select_one('td.subtext')
            points = 0
            author = ''
            age = ''
            comment_count = 0
            if subtext:
                pts_tag = subtext.select_one('span.score')
                if pts_tag:
                    try:
                        points = int(pts_tag.get_text().split()[0])
                    except Exception:
                        points = 0
                author_tag = subtext.select_one('a.hnuser')
                author = author_tag.get_text(strip=True) if author_tag else ''
                age_tag = subtext.select_one('span.age')
                age = age_tag.get_text(strip=True) if age_tag else ''
                comments_tag = subtext.select_one('a[href*="item?id="]:last-child')
                if comments_tag:
                    comment_text = comments_tag.get_text(strip=True)
                    if comment_text.endswith('comments'):
                        try:
                            comment_count = int(comment_text.split()[0])
                        except Exception:
                            comment_count = 0
            items.append({
                "item_id": story_id,
                "title": title,
                "link": link,
                "points": points,
                "author": author,
                "age": age,
                "comment_count": comment_count,
                "permalink": f"/item?id={story_id}",
                "page_url": page_url,
            })
        return items

    def _parse_item(self, soup: BeautifulSoup, page_url: str) -> List[Dict]:
        items: List[Dict] = []
        # The main story appears as a table row with class 'fatitem' (or similar).
        story_row = soup.select_one('tr.fatitem')
        if story_row:
            story_id = page_url.split('id=')[-1]
            title_tag = soup.select_one('title')
            title = title_tag.get_text(strip=True) if title_tag else ''
            link_tag = soup.select_one('a.storylink')
            link = link_tag['href'] if link_tag and link_tag.has_attr('href') else ''
            subtext = soup.select_one('td.subtext')
            points = 0
            author = ''
            age = ''
            if subtext:
                pts_tag = subtext.select_one('span.score')
                if pts_tag:
                    try:
                        points = int(pts_tag.get_text().split()[0])
                    except Exception:
                        points = 0
                author_tag = subtext.select_one('a.hnuser')
                author = author_tag.get_text(strip=True) if author_tag else ''
                age_tag = subtext.select_one('span.age')
                age = age_tag.get_text(strip=True) if age_tag else ''
            items.append({
                "item_id": story_id,
                "title": title,
                "link": link,
                "points": points,
                "author": author,
                "age": age,
                "permalink": f"/item?id={story_id}",
                "page_url": page_url,
                "content_type": "post",
            })
        # Comments are in rows with class 'comment'
        for comment in soup.select('tr.comment'):
            comment_id = comment.get('id')
            author_tag = comment.select_one('a.hnuser')
            author = author_tag.get_text(strip=True) if author_tag else ''
            text_tag = comment.select_one('span.commtext')
            text = text_tag.get_text(strip=True) if text_tag else ''
            age_tag = comment.select_one('span.age')
            age = age_tag.get_text(strip=True) if age_tag else ''
            # Parent ID is stored in a data-parent attribute on the comment row if present
            parent = comment.get('data-parent') or ''
            # Indentation is expressed via the width of an img spacer – we approximate
            indent_img = comment.select_one('img.indent')
            indentation = 0
            if indent_img and indent_img.has_attr('width'):
                try:
                    indentation = int(int(indent_img['width']) / 40)  # each level 40px
                except Exception:
                    indentation = 0
            items.append({
                "item_id": comment_id,
                "author": author,
                "text": text,
                "age": age,
                "parent": parent,
                "indentation": indentation,
                "permalink": f"/item?id={comment_id}",
                "page_url": page_url,
                "content_type": "comment",
            })
        return items

    def parse(self, html: str, page_url: str) -> List[Dict]:
        soup = BeautifulSoup(html, "html.parser")
        # Heuristic: if the page contains a table row with class 'athing' it is a listing.
        if soup.select_one('tr.athing'):
            return self._parse_listing(soup, page_url)
        # If URL contains 'item?id=' we treat it as an item page.
        if "item?id=" in page_url:
            return self._parse_item(soup, page_url)
        # Fallback – return empty list.
        return []

# Register the parser under the name used in the sites config.
register("hackernews", HackerNewsParser)

