"""Read headline cards from an AFR section page (no login or LLM required).

Usage: python -m services.afr_news --url https://www.afr.com/property/residential
"""
import argparse
import json
import hashlib
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from html.parser import HTMLParser
from urllib.parse import urljoin

import requests

DEFAULT_URL = 'https://www.afr.com/property/residential'
_VOID_TAGS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
              'link', 'meta', 'param', 'source', 'track', 'wbr'}


class _HeadlineParser(HTMLParser):
    def __init__(self, url):
        super().__init__(convert_charrefs=True)
        self.url = url
        self.items = []
        self.depth = 0
        self.tile_depth = None
        self.card = None
        self.capture_title = False
        self.capture_time = False
        self.title_parts = []
        self.time_parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag not in _VOID_TAGS:
            self.depth += 1
        if attrs.get('data-testid') == 'StoryTileBase':
            self.tile_depth = self.depth
            self.card = {'title': '', 'time': None, 'url': None}
            self.title_parts, self.time_parts = [], []
        if self.card is None:
            return
        if tag == 'a' and attrs.get('data-testid') == 'headlineLink':
            self.capture_title = True
            self.card['url'] = urljoin(self.url, attrs.get('href', ''))
        if tag == 'img' and not self.card.get('thumbnail_url'):
            image = attrs.get('src') or attrs.get('data-src')
            if image and not image.startswith('data:'):
                self.card['thumbnail_url'] = urljoin(self.url, image)
        if tag == 'time':
            self.capture_time = True
            self.card['time'] = attrs.get('datetime')

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_data(self, data):
        if self.card is None:
            return
        if self.capture_title:
            self.title_parts.append(data)
        if self.capture_time:
            self.time_parts.append(data)

    def handle_endtag(self, tag):
        if tag in _VOID_TAGS:
            return
        if self.card is not None:
            if tag == 'a':
                self.capture_title = False
            if tag == 'time':
                self.capture_time = False
            if self.depth == self.tile_depth:
                self.card['title'] = ' '.join(''.join(self.title_parts).split())
                self.card['time'] = self.card['time'] or ''.join(self.time_parts).strip() or None
                if self.card['title'] and self.card['url']:
                    self.items.append(self.card)
                self.card = None
                self.tile_depth = None
        self.depth = max(0, self.depth - 1)


def parse_afr_news(html, url=DEFAULT_URL):
    """Return visible article-card titles and raw page timestamps, deduplicated by URL."""
    parser = _HeadlineParser(url)
    parser.feed(html)
    return list({item['url']: item for item in parser.items}.values())


def fetch_afr_news(url=DEFAULT_URL, timeout=30):
    """Read one listing page; preserve its time text without guessing a timezone.

    Does not fetch article bodies or follow pagination. Raises on blocked pages
    or an unrecognised page layout rather than reporting an empty successful list.
    """
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    items = parse_afr_news(response.text, response.url)
    if not items:
        raise ValueError('未读取到 AFR 新闻卡片：页面可能被拦截，或栏目结构已变化')
    return items


def article_candidates(items, days, now=None, *, topic="房产", source_name="AFR · Property", skipped=None):
    """Adapt listing cards to UI candidates using the same rolling cutoff as YouTube.

    AFR's unzoned timestamps are Sydney local time (including daylight saving).
    Updated timestamps are treated as publication timestamps.
    """
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    candidates = []
    for item in items:
        value = re.sub(r'^Updated\s*', '', item['time'] or '', flags=re.I).strip()
        try:
            published = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            value = value.replace('–', '-').replace('—', '-')
            try:
                published = datetime.strptime(value, '%b %d, %Y - %I.%M%p')
            except ValueError:
                if skipped is not None:
                    skipped.append(item)
                continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=ZoneInfo('Australia/Sydney'))
        published = published.astimezone(timezone.utc)
        if published < cutoff:
            continue
        candidates.append({
            'video_id': 'afr_' + hashlib.sha256(item['url'].encode()).hexdigest()[:16],
            'source_type': 'article', 'publisher': 'AFR', 'title': item['title'], 'url': item['url'],
            'channel_name': source_name, 'thumbnail_url': item.get('thumbnail_url'),
            'published_at': published.isoformat().replace('+00:00', 'Z'),
            'classified_topics': [topic], 'reason': f'{source_name} 栏目',
        })
    return candidates


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default=DEFAULT_URL, help='AFR 栏目网址')
    args = parser.parse_args()
    print(json.dumps(fetch_afr_news(args.url), ensure_ascii=False, indent=2))
