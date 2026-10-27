"""Home Affairs minister media releases and article text."""
import hashlib
import json
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
from playwright.sync_api import sync_playwright

DEFAULT_URL = ('https://minister.homeaffairs.gov.au/ministers-for-home-affairs/'
               'the-hon-tony-burke-mp')
HOST = 'minister.homeaffairs.gov.au'
TZ = ZoneInfo('Australia/Sydney')
API_URL = f'https://{HOST}/_layouts/15/api/MinistersData.aspx/GetMediaHubData'


def validate_source_url(url):
    parsed = urlparse(url)
    if (parsed.scheme != 'https' or parsed.hostname != HOST
            or not parsed.path.startswith('/ministers-for-home-affairs/')):
        raise ValueError('Home Affairs Minister 模组需要部长主页网址')


def validate_article_url(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname != HOST or '/Pages/' not in parsed.path:
        raise ValueError('Home Affairs Minister 文章网址无效')


def _context(html):
    web = re.search(r'"webServerRelativeUrl":"([^"]+)"', html)
    title = re.search(r'"webTitle":"([^"]+)"', html)
    if not web or not title:
        raise ValueError('部长主页缺少 SharePoint 站点信息')
    return web.group(1), json.loads('"' + title.group(1) + '"')


def _session():
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                                          'AppleWebKit/537.36 Chrome/140 Safari/537.36'})
    return session


def fetch_home_affairs_news(url=DEFAULT_URL, days=30, *, now=None, log=print):
    """Return this minister's recent Media Releases as generic article sources."""
    validate_source_url(url)
    if type(days) is not int or days < 1:
        raise ValueError('days 必须为正整数')
    today = (now or datetime.now(TZ)).astimezone(TZ).date()
    start = today - timedelta(days=days - 1)
    with _session() as session:
        page = session.get(url, timeout=45)
        page.raise_for_status()
        validate_source_url(page.url)
        web_url, publisher = _context(page.text)
        response = session.post(API_URL, json={'webUrl': web_url},
                                headers={'Referer': page.url}, timeout=45)
        response.raise_for_status()
        payload = response.json().get('d', {})
    if not payload.get('success') or not isinstance(payload.get('data'), list):
        raise RuntimeError('Home Affairs 媒体列表接口返回异常')
    rows = {}
    for item in payload['data']:
        if str(item.get('contentType', '')).lower() != 'mediarelease':
            continue
        try:
            date = datetime.strptime(item['date'], '%d %b %Y').date()
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError('Home Affairs 列表条目日期无效') from error
        if not start <= date <= today:
            continue
        link = item.get('url', '')
        validate_article_url(link)
        rows[link] = {
            'video_id': 'home_affairs_' + hashlib.sha256(link.encode()).hexdigest()[:16],
            'source_type': 'article',
            'publisher': publisher,
            'channel_name': publisher,
            'title': str(item.get('title') or '').strip(),
            'url': link,
            'published_at': datetime.combine(date, datetime.min.time(), TZ).isoformat(),
            'thumbnail_url': None,
        }
    log(f'Home Affairs · {publisher}：{start} 至 {today}，Media Release {len(rows)} 篇')
    return sorted(rows.values(), key=lambda row: row['published_at'], reverse=True)


def fetch_home_affairs_article(url):
    """Download one selected media release and return its readable body text."""
    validate_article_url(url)
    with _session() as session:
        response = session.get(url, timeout=45)
        response.raise_for_status()
        validate_article_url(response.url)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        try:
            page = browser.new_page(java_script_enabled=False)
            page.set_content(response.text, wait_until='domcontentloaded')
            body = page.locator('.content .ms-rtestate-field').first
            text = body.evaluate('''el => {
                const copy = el.cloneNode(true);
                copy.querySelectorAll('script,style,nav,aside,figure').forEach(e=>e.remove());
                return Array.from(copy.querySelectorAll('p,h2,h3,h4,li,blockquote'))
                    .filter(e=>!e.querySelector('p,li,blockquote'))
                    .map(e=>e.textContent.trim()).filter(Boolean).join('\\n\\n');
            }''')
        finally:
            browser.close()
    if not text.strip():
        raise ValueError('Home Affairs 文章正文为空：' + url)
    return text
