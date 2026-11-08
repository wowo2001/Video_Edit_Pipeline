"""CIS opinions adapter, with the same candidate and article interfaces as Fair Work."""
import hashlib
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin, parse_qsl, urlencode
from zoneinfo import ZoneInfo

import requests
from playwright.sync_api import sync_playwright

DEFAULT_URL = 'https://www.cis.org.au/commentary/opinions/'
PUBLISHER = 'Centre for Independent Studies'
TZ = ZoneInfo('Australia/Sydney')


def validate_url(url, *, article=False):
    parsed = urlparse(url)
    prefix = '/commentary/opinion/' if article else '/commentary/opinions/'
    if (parsed.scheme != 'https' or parsed.hostname not in ('cis.org.au', 'www.cis.org.au')
            or not (parsed.path.rstrip('/')+'/' ).startswith(prefix)):
        raise ValueError('CIS 模组需要 CIS Opinions 栏目或文章网址')


def load(page, session, url, *, article=False):
    validate_url(url, article=article)
    response = session.get(url, timeout=45)
    response.raise_for_status()
    validate_url(response.url, article=article)
    page.set_content(response.text, wait_until='domcontentloaded')


def parse_listing(page, url):
    rows = page.locator('a[href*="/commentary/opinion/"]:has(time)').evaluate_all('''els => els.map(el => ({
        title: el.querySelector('.elementor-widget-theme-post-title')?.textContent.trim(),
        url: el.getAttribute('href'), date: el.querySelector('time')?.textContent.trim(),
        image: el.querySelector('img')?.getAttribute('src')
    }))''')
    if not rows:
        raise ValueError('CIS 列表未找到文章，页面结构可能已改变')
    output = []
    for row in rows:
        if not row['title'] or not row['date'] or not row['url']:
            raise ValueError('CIS 条目缺少标题、链接或日期')
        date = datetime.strptime(row['date'], '%B %d, %Y').date()
        link = urljoin(url, row['url']).split('#')[0]
        validate_url(link, article=True)
        output.append(dict(video_id='cis_'+hashlib.sha256(link.encode()).hexdigest()[:16],
            source_type='article', publisher=PUBLISHER, channel_name=PUBLISHER,
            title=row['title'], url=link,
            published_at=datetime.combine(date, datetime.min.time(), TZ).isoformat(),
            thumbnail_url=urljoin(url,row['image']) if row['image'] else None))
    next_link = page.locator('a.page-numbers.next')
    next_url = urljoin(url, next_link.first.get_attribute('href')) if next_link.count() else None
    if next_url:
        parsed = urlparse(next_url)
        query = dict(parse_qsl(parsed.query))
        # CIS caches the Elementor-only link as page one; WordPress paged works.
        page_number = next((v for k, v in query.items() if k.startswith('e-page-')), None)
        if page_number:
            query['paged'] = page_number
            next_url = parsed._replace(query=urlencode(query)).geturl()
    return output, next_url


def parse_article(page):
    body = page.locator('.elementor-widget-theme-post-content').first
    if not body.count():
        raise ValueError('CIS 文章正文容器缺失')
    text = body.evaluate('''el => {
        const copy=el.cloneNode(true);
        copy.querySelectorAll('script,style,nav,aside,form,.sharedaddy').forEach(e=>e.remove());
        return Array.from(copy.querySelectorAll('p,h2,h3,h4,li,blockquote'))
          .filter(e=>!e.querySelector('p,li,blockquote'))
          .map(e=>e.textContent.trim()).filter(Boolean).join('\\n\\n');
    }''')
    if not text.strip():
        raise ValueError('CIS 文章正文为空')
    return text


def fetch_cis_article(url):
    validate_url(url, article=True)
    with requests.Session() as session, sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        try:
            page = browser.new_page(java_script_enabled=False)
            page.route('**/*', lambda route: route.abort())
            load(page, session, url, article=True)
            return parse_article(page)
        finally:
            browser.close()


def fetch_cis_news(url=DEFAULT_URL, days=3, *, now=None, log=print):
    validate_url(url)
    if type(days) is not int or days < 1:
        raise ValueError('days 必须为正整数')
    today = (now or datetime.now(TZ)).astimezone(TZ).date()
    start = today - timedelta(days=days-1)
    result, seen = {}, set()
    with requests.Session() as session, sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        try:
            page = browser.new_page(java_script_enabled=False)
            page.route('**/*', lambda route: route.abort())
            current = url
            while current:
                if current in seen:
                    raise RuntimeError('CIS 分页重复：'+current)
                seen.add(current)
                load(page, session, current)
                rows, next_url = parse_listing(page, current)
                dates = [datetime.fromisoformat(row['published_at']).date() for row in rows]
                for row, date in zip(rows, dates):
                    if start <= date <= today:
                        result[row['url']] = row
                log(f'CIS 已读取第 {len(seen)} 页，范围内 {len(result)} 篇')
                if max(dates) < start:
                    break
                current = next_url
        finally:
            browser.close()
    return sorted(result.values(), key=lambda row: row['published_at'], reverse=True)
