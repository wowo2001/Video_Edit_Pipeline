"""Fair Work Ombudsman media releases: source-compatible lists and article text."""
import hashlib
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin, urlencode, parse_qsl
from zoneinfo import ZoneInfo

import requests
from playwright.sync_api import sync_playwright

DEFAULT_URL = 'https://www.fairwork.gov.au/newsroom/media-releases'
PUBLISHER = 'Fair Work Ombudsman'
TZ = ZoneInfo('Australia/Sydney')


def validate_url(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname != 'www.fairwork.gov.au' or not parsed.path.startswith('/newsroom/media-releases'):
        raise ValueError('Fair Work 模组需要 Fair Work Ombudsman Media releases 网址')


def load(page, session, url):
    validate_url(url)
    response = session.get(url, timeout=45)
    response.raise_for_status()
    validate_url(response.url)
    page.set_content(response.text, wait_until='domcontentloaded')


def article_text(page, session, url):
    load(page, session, url)
    body = page.locator('article.node--type-news-media-releases > .node__content > .field--name-body').first
    text = body.evaluate('''el => {
        const copy = el.cloneNode(true);
        copy.querySelectorAll('.embedded-entity,script,style,nav,aside').forEach(e=>e.remove());
        return Array.from(copy.querySelectorAll('p,h2,h3,h4,li'))
            .filter(e=>!e.querySelector('p,li'))
            .map(e=>e.textContent.trim()).filter(Boolean).join('\\n\\n');
    }''')
    if not text.strip():
        raise ValueError('Fair Work 文章正文为空：' + url)
    return text


def fetch_fair_work_article(url):
    with requests.Session() as session, sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        try:
            page = browser.new_page(java_script_enabled=False)
            page.route('**/*', lambda route: route.abort())
            return article_text(page, session, url)
        finally:
            browser.close()


def fetch_fair_work_news(url=DEFAULT_URL, days=3, *, now=None, log=print):
    validate_url(url)
    today = (now or datetime.now(TZ)).astimezone(TZ).date()
    start = today - timedelta(days=days-1)
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query))
    for key in ('year', 'month', 'page', 'updated[min]', 'updated[max]'):
        query.pop(key, None)
    query.update({'updated[min]': start.isoformat(), 'updated[max]': today.isoformat()})
    log(f'Fair Work 日期筛选：{start} 至 {today}（悉尼日期）')
    result, seen_pages = {}, set()
    with requests.Session() as session, sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        try:
            page = browser.new_page(java_script_enabled=False)
            page.route('**/*', lambda route: route.abort())
            current = parsed._replace(query=urlencode(query)).geturl()
            while current:
                if current in seen_pages:
                    raise RuntimeError('Fair Work 分页重复：' + current)
                seen_pages.add(current)
                load(page, session, current)
                rows = page.locator('.views-row').evaluate_all('''els => els.map(el=>({
                    title:el.querySelector('h2 a')?.textContent.trim(),
                    url:el.querySelector('h2 a')?.getAttribute('href'),
                    date:el.querySelector('.date-line')?.textContent.trim(),
                    image:el.querySelector('img')?.getAttribute('src')
                }))''')
                page_dates = []
                for row in rows:
                    if not row['url'] or not row['date']:
                        raise ValueError('Fair Work 列表条目缺少标题链接或日期')
                    date = datetime.strptime(row['date'].rsplit('|',1)[-1].strip(), '%d %b %Y').date()
                    page_dates.append(date)
                    if not start <= date <= today:
                        continue
                    link = urljoin(current,row['url'])
                    validate_url(link)
                    result[link] = dict(video_id='fair_work_'+hashlib.sha256(link.encode()).hexdigest()[:16],
                        source_type='article',publisher=PUBLISHER,channel_name=PUBLISHER,
                        title=row['title'],url=link,
                        published_at=datetime.combine(date,datetime.min.time(),TZ).isoformat(),
                        thumbnail_url=urljoin(current,row['image']) if row['image'] else None)
                log(f'Fair Work 已读取第 {len(seen_pages)} 页，范围内 {len(result)} 篇')
                # Releases are newest first; stop after a complete page before the cutoff.
                if page_dates and max(page_dates) < start:
                    break
                next_link = page.locator('.pager__item--next a')
                if next_link.count():
                    next_url = urljoin(current,next_link.first.get_attribute('href'))
                    next_query = {**query, **dict(parse_qsl(urlparse(next_url).query))}
                    current = urlparse(next_url)._replace(query=urlencode(next_query)).geturl()
                else:
                    current = None
        finally:
            browser.close()
    return sorted(result.values(),key=lambda row:row['published_at'],reverse=True)
