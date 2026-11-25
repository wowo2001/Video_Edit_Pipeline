"""Domain topic listings and article text, using public page data."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urljoin
from playwright.sync_api import sync_playwright

DEFAULT_URL = 'https://www.domain.com.au/topics/owners/'
PUBLISHER = 'Domain'


def validate_url(url, *, article=False):
    p = urlsplit(url)
    if p.scheme != 'https' or p.hostname not in ('domain.com.au', 'www.domain.com.au'):
        raise ValueError('Domain 模组需要 https://www.domain.com.au 的网址')



def load(page, url, *, article=False):
    validate_url(url, article=article)
    response = page.goto(url, wait_until='domcontentloaded', timeout=60000)
    if not response or response.status >= 400:
        raise RuntimeError(f'Domain 页面访问失败：HTTP {response.status if response else "unknown"}')
    validate_url(page.url, article=article)
    page.locator('#__NEXT_DATA__').wait_for(state='attached', timeout=15000)
    return json.loads(page.locator('#__NEXT_DATA__').inner_text())['props']['pageProps']


def parse_listing(data):
    articles = data.get('data', {}).get('articles')
    if not isinstance(articles, list):
        raise ValueError('这个 Domain 页面没有文章列表，请填写栏目页面')
    rows = []
    for a in articles:
        url = a['canonicalUrl']
        if urlsplit(url).hostname not in ('domain.com.au', 'www.domain.com.au'):
            continue  # Linked partner sites require their own article adapters.
        validate_url(url, article=True)
        published = datetime.fromisoformat(a['publishedDate'])
        if published.tzinfo is None:
            raise ValueError('Domain 发布时间缺少时区')
        image = a.get('indexImage') or a.get('featuredImage') or {}
        rows.append(dict(video_id='domain_'+hashlib.sha256(url.encode()).hexdigest()[:16],
            source_type='article', publisher=PUBLISHER, channel_name=PUBLISHER,
            title=a['title'], url=url, published_at=published.isoformat(),
            thumbnail_url=image.get('sizes', {}).get('full', {}).get('url')))
    return rows


def parse_article(page, data):
    content = data['articleData'].get('content')
    if not content or not isinstance(content, str):
        raise ValueError('Domain 文章正文缺失')
    text = page.evaluate('''html => {
        const doc = new DOMParser().parseFromString(html, 'text/html');
        doc.querySelectorAll('script,style,nav,aside,figure,form,button,x-placeholder').forEach(e=>e.remove());
        return Array.from(doc.querySelectorAll('p,h2,h3,h4,li,blockquote'))
          .filter(e=>!e.querySelector('p,li,blockquote'))
          .map(e=>e.textContent.trim()).filter(Boolean).join('\\n\\n');
    }''', content)
    if not text.strip():
        raise ValueError('Domain 文章正文为空')
    return text


def fetch_domain_news(url=DEFAULT_URL, days=3, *, now=None, log=print):
    validate_url(url)
    if type(days) is not int or days < 1:
        raise ValueError('days 必须为正整数')
    current = now or datetime.now(timezone.utc)
    cutoff = current - timedelta(days=days)
    result, seen = {}, set()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        try:
            page = browser.new_page()
            while url:
                if url in seen:
                    raise RuntimeError('Domain 分页重复：'+url)
                seen.add(url)
                data = load(page, url)
                rows = parse_listing(data)
                dates = [datetime.fromisoformat(r['published_at']) for r in rows]
                for row, date in zip(rows, dates):
                    if cutoff <= date <= current:
                        result[row['url']] = row
                log(f'Domain 已读取第 {len(seen)} 页，范围内 {len(result)} 篇')
                if not dates or max(dates) < cutoff:
                    break
                number = int(data['pageNumber']) + 1
                links = page.locator('a[href]').evaluate_all('(els)=>els.map(e=>e.getAttribute("href"))')
                next_path = next((h for h in links if h.split('?')[0].endswith(f'/page/{number}/')), None)
                url = urljoin(url, next_path) if next_path else None
        finally:
            browser.close()
    return sorted(result.values(), key=lambda r:r['published_at'], reverse=True)


def fetch_domain_article(url):
    validate_url(url, article=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        try:
            page = browser.new_page()
            return parse_article(page, load(page, url, article=True))
        finally:
            browser.close()
