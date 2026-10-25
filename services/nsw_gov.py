"""NSW Government news listings and full articles using the site's date filter.

python -m services.nsw_gov --days 30 --output work/nsw_news.json
Dates use Sydney calendar days, inclusive of today (1 day means today).
"""
import argparse
import copy
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse, urljoin, urlencode, parse_qsl
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright

DEFAULT_URL = 'https://www.nsw.gov.au/departments-and-agencies/fair-trading/news'
TZ = ZoneInfo('Australia/Sydney')


def validate_url(url):
    if urlparse(url).scheme != 'https' or urlparse(url).hostname != 'www.nsw.gov.au':
        raise ValueError('NSW Government 模组需要 https://www.nsw.gov.au 网址')


def read_article(page, url):
    validate_url(url)
    page.goto(url, wait_until='domcontentloaded', timeout=60000)
    page.locator('main .nsw-wysiwyg-content').first.wait_for(timeout=30000)
    body = page.locator('main .nsw-wysiwyg-content').evaluate_all('''els => els.map(el => {
        const clone=el.cloneNode(true);
        clone.querySelectorAll('script,style,nav,aside,figure').forEach(e=>e.remove());
        return Array.from(clone.querySelectorAll('p,h2,h3,h4,li')).filter(e=>!e.querySelector('p,li'))
          .map(e=>e.textContent.trim()).filter(Boolean).join('\\n\\n');
    }).filter(Boolean).join('\\n\\n')''')
    intro=page.locator('main .nsw-intro')
    lead='\n\n'.join(intro.all_inner_texts()).strip()
    if lead and not body.startswith(lead):body=lead+'\n\n'+body
    if not body.strip():raise ValueError('NSW 文章正文为空：'+url)
    return body


def fetch_nsw_article(url):
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        try:return read_article(browser.new_page(),url)
        finally:browser.close()


def fetch_nsw_news(url=DEFAULT_URL, days=30, *, include_content=True, now=None, log=print, page_size=50):
    validate_url(url)
    if type(days) is not int or days<1:raise ValueError('days 必须为正整数')
    today=(now or datetime.now(TZ)).astimezone(TZ).date()
    start=today-timedelta(days=days-1)
    parsed=urlparse(url);query=dict(parse_qsl(parsed.query));query['date']=f'{start},{today}'
    filtered=parsed._replace(query=urlencode(query)).geturl()
    log(f'NSW 日期筛选：{start} 至 {today}（悉尼日期，含首尾）')
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        try:
            page=browser.new_page()
            # Capture this listing's own agency/topic filters instead of hardcoding Fair Trading.
            with page.expect_response(lambda r:'/api/v1/elasticsearch/' in r.url and r.request.method=='POST' and any('script' in f or 'range' in f for f in (r.request.post_data_json or {}).get('query',{}).get('bool',{}).get('filter',[])),timeout=60000) as pending:
                page.goto(filtered,wait_until='domcontentloaded',timeout=60000)
            response=pending.value
            if not response.ok:raise RuntimeError(f'NSW 列表请求失败：{response.status}')
            payload=response.request.post_data_json
            if not any('script' in f or 'range' in f for f in payload['query']['bool']['filter']):
                raise ValueError('网页未应用日期筛选，停止读取未筛选列表')
            offset=0;items={};seen=set()
            while True:
                request=copy.deepcopy(payload);request.update(size=page_size,**{'from':offset})
                result=page.request.post(response.url,data=request,timeout=60000)
                if not result.ok:raise RuntimeError(f'NSW 分页失败：{result.status}')
                data=result.json()
                if data.get('timed_out') or data.get('_shards',{}).get('failed'):raise RuntimeError('NSW 搜索返回不完整结果')
                hits=data['hits']['hits'];total=data['hits']['total'];total=total['value'] if isinstance(total,dict) else total
                if not hits:
                    if offset<total:raise RuntimeError('NSW 分页提前结束')
                    break
                for hit in hits:
                    if hit['_id'] in seen:raise RuntimeError('NSW 分页重复，无法保证结果完整')
                    seen.add(hit['_id']);src=hit['_source']
                    def first(key,default=''):
                        value=src.get(key,default)
                        return value[0] if isinstance(value,list) and value else value
                    link=urljoin(url,first('url'));validate_url(link)
                    # display_date is the date displayed on the listing, stored at UTC midnight.
                    date=datetime.fromtimestamp(int(first('display_date')),ZoneInfo('UTC')).date()
                    if not start<=date<=today:continue
                    items[link]={'video_id':'nsw_'+hashlib.sha256(link.encode()).hexdigest()[:16],
                        'source_type':'article','publisher':'NSW Government','channel_name':'NSW Government',
                        'title':first('title'),'url':link,'published_at':datetime.combine(date,datetime.min.time(),TZ).isoformat(),
                        'content':''}
                offset+=len(hits);log(f'NSW 列表已读取 {offset}/{total} 条')
                if offset>=total:break
            rows=list(items.values())
            if include_content:
                for number,item in enumerate(rows,1):
                    item['content']=read_article(page,item['url'])
                    image=page.locator('meta[property="og:image"]')
                    item['thumbnail_url']=image.first.get_attribute('content') if image.count() else None
                    log(f'NSW 正文 {number}/{len(rows)}：{item["title"]}（{len(item["content"])} 字符）')
            return rows
        finally:browser.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default=DEFAULT_URL);parser.add_argument('--days',type=int,default=30)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();rows=fetch_nsw_news(args.url,args.days)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
    print(f'完成：{len(rows)} 篇，保存至 {args.output}')
