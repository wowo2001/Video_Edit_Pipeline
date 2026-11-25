"""Guardian section RSS candidates and full article text, without login."""
import argparse
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit
from xml.etree import ElementTree

import requests
from playwright.sync_api import sync_playwright

DEFAULT_URL = 'https://www.theguardian.com/australia-news'
PUBLISHER = 'The Guardian'
MEDIA = '{http://search.yahoo.com/mrss/}'


def validate_url(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in ('theguardian.com', 'www.theguardian.com'):
        raise ValueError('Guardian 模组需要 https://www.theguardian.com 的栏目或文章网址')
    return parsed


def article_url(url):
    parsed = validate_url(url)
    return (bool(re.search(r'/\d{4}/[a-z]{3}/\d{1,2}/', parsed.path))
            and not any(f'/{kind}/' in parsed.path for kind in ('live', 'video', 'audio', 'gallery', 'picture')))


def parse_guardian_news(xml, days=3, *, now=None):
    if type(days) is not int or days < 1:
        raise ValueError('days 必须为正整数')
    current = now or datetime.now(timezone.utc)
    cutoff = current - timedelta(days=days)
    channel = ElementTree.fromstring(xml).find('channel')
    if channel is None:
        raise ValueError('Guardian 返回的内容不是栏目 RSS')
    result = {}
    for item in channel.findall('item'):
        url = (item.findtext('link') or '').strip()
        if not url or not article_url(url):
            continue
        title = (item.findtext('title') or '').strip()
        date = item.findtext('pubDate')
        if not title or not date:
            raise ValueError('Guardian RSS 文章缺少标题或发布时间')
        published = parsedate_to_datetime(date).astimezone(timezone.utc)
        if not cutoff <= published <= current:
            continue
        images = item.findall(f'{MEDIA}content')
        image = next((i.get('url') for i in reversed(images) if i.get('url')), None)
        result[url] = dict(video_id='guardian_'+hashlib.sha256(url.encode()).hexdigest()[:16],
                           source_type='article', publisher=PUBLISHER, channel_name=PUBLISHER,
                           title=title, url=url, published_at=published.isoformat(),
                           thumbnail_url=image)
    return sorted(result.values(), key=lambda row: row['published_at'], reverse=True)


def fetch_guardian_news(url=DEFAULT_URL, days=3, *, now=None, log=print):
    parsed = validate_url(url)
    if article_url(url):
        raise ValueError('抓取列表请填写 Guardian 栏目页，而不是单篇文章')
    path = parsed.path.rstrip('/')
    feed = urlunsplit((parsed.scheme, parsed.netloc, path if path.endswith('/rss') else path+'/rss', '', ''))
    response = requests.get(feed, timeout=30)
    response.raise_for_status()
    validate_url(response.url)
    rows = parse_guardian_news(response.content, days, now=now)
    log(f'Guardian RSS：范围内 {len(rows)} 篇文章（仅覆盖订阅源近期条目，跳过直播/视频/音频/图集/漫画）')
    return rows


def parse_guardian_article(page):
    body = page.locator('.article-body-commercial-selector').first
    if not body.count():
        raise ValueError('Guardian 文章正文容器缺失，可能是特殊页面或访问受限')
    text = body.evaluate(r'''el => {
        const copy = el.cloneNode(true);
        copy.querySelectorAll(`script,style,nav,aside,figure,form,button,[data-print-layout="hide"],
            [data-component="rich-link"],[data-component="newsletter-signup"],
            [data-gu-name="ad-placeholder"]`).forEach(e => e.remove());
        return Array.from(copy.querySelectorAll('p,h2,h3,h4,li,blockquote'))
            .filter(e => !e.querySelector('p,li,blockquote'))
            .map(e => e.textContent.trim()).filter(Boolean)
            .filter(t => !/^(Sign up (?:for|to)|Get our .*?(?:newsletter|free app|daily political email)|First Thing:|Explore more on these topics)/i.test(t))
            .join('\n\n');
    }''')
    if not text.strip():
        raise ValueError('Guardian 文章正文为空')
    return text


def fetch_guardian_article(url):
    if not article_url(url):
        raise ValueError('需要 Guardian 普通文章网址，暂不支持直播、视频、音频、图集和漫画')
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    validate_url(response.url)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        try:
            page = browser.new_page(java_script_enabled=False)
            page.route('**/*', lambda route: route.abort())
            page.set_content(response.text, wait_until='domcontentloaded')
            return parse_guardian_article(page)
        finally:
            browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default=DEFAULT_URL)
    parser.add_argument('--days', type=int, default=3)
    parser.add_argument('--article', action='store_true')
    args = parser.parse_args()
    print(fetch_guardian_article(args.url) if args.article else
          json.dumps(fetch_guardian_news(args.url, args.days), ensure_ascii=False, indent=2))
