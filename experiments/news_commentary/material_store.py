"""Persist prepared source material, before commentary planning."""
import json
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from config import POSTGRESQL_PASSWORD, POSTGRESQL_USER


def publication_time(value):
    if not value:
        return None
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        result = datetime.strptime(text, '%Y%m%d')
    else:
        result = datetime.fromisoformat(text.replace('Z', '+00:00'))
    return result if result.tzinfo else result.replace(tzinfo=timezone.utc)


def material_records(root):
    root = Path(root)
    config = json.loads((root / 'experiment_input.json').read_text(encoding='utf-8'))
    catalog = json.loads((root / 'source_catalog.json').read_text(encoding='utf-8'))
    inputs = {item['url']: item for item in config['sources']}
    records = []
    for source in catalog:
        item = inputs[source['url']]
        context = source['context']
        folder = root / 'sources' / source['source_id']
        if source['source_type'] == 'article':
            article = json.loads((folder / 'article.json').read_text(encoding='utf-8'))
            content = {'text': article['content']}
            if not content['text'].strip():
                raise ValueError(f"{source['source_id']} 文章正文为空，不能入库")
        else:
            transcript = json.loads((folder / 'subtitles.json').read_text(encoding='utf-8'))
            if not transcript.get('utterances'):
                raise ValueError(f"{source['source_id']} 字幕为空，不能入库")
            content = {'transcript': transcript}
        title = item.get('title') or context.get('title')
        if not title:
            raise ValueError(f"{source['source_id']} 缺少标题，不能入库")
        records.append((title, source['url'], source['source_type'],
                        source.get('publisher') or None,
                        item.get('asr_language') or None,
                        publication_time(item.get('published_at') or context.get('published_at')),
                        Jsonb(content)))
    return records


def store_materials(config, root):
    records = material_records(root)
    print(f'[database] 开始写入 news_materials：{len(records)} 条素材', flush=True)
    with psycopg.connect(
        host='192.168.5.113',
        port=5432,
        dbname='news',
        user=POSTGRESQL_USER, password=POSTGRESQL_PASSWORD, connect_timeout=10,
        options='-c statement_timeout=30000 -c lock_timeout=10000',
    ) as conn:
        with conn.cursor() as cur:
            cur.executemany('''
                INSERT INTO public.news_materials
                    (title, url, source_type, publisher, language, published_at, content)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (url) DO UPDATE SET
                    title = EXCLUDED.title,
                    source_type = EXCLUDED.source_type,
                    publisher = COALESCE(EXCLUDED.publisher, news_materials.publisher),
                    language = COALESCE(EXCLUDED.language, news_materials.language),
                    published_at = COALESCE(EXCLUDED.published_at, news_materials.published_at),
                    content = EXCLUDED.content,
                    updated_at = NOW()
            ''', records)
    print(f'[database] 入库完成：{len(records)} 条素材（按 URL 新增或更新）', flush=True)
