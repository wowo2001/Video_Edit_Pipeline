"""Persist prepared source material, before commentary planning."""
import json
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from config import POSTGRESQL_PASSWORD, POSTGRESQL_USER


def connect():
    return psycopg.connect(
        host='192.168.5.113', port=5432, dbname='news',
        user=POSTGRESQL_USER, password=POSTGRESQL_PASSWORD, connect_timeout=10,
        options='-c statement_timeout=30000 -c lock_timeout=10000',
    )


def restore_materials(config, root, force=False):
    from core.path import ProjectPaths
    from experiments.news_commentary.pipeline import source_type, save

    stages = ('transcribe', 'merge', 'speakers', 'gender', 'recognise')
    if force:
        for number, item in enumerate(config['sources'], 1):
            folder = Path(root) / 'sources' / f'source_{number:02d}'
            for stage in (*stages, 'database'):
                (folder / f'.{stage}.done').unlink(missing_ok=True)
            if source_type(item) == 'article':
                (folder / '.download.done').unlink(missing_ok=True)
        print('[database] 强制重新预处理，跳过数据库缓存', flush=True)
        return
    with connect() as conn, conn.cursor() as cur:
        cur.execute('''SELECT url, source_type, title, publisher, language, published_at, content
                       FROM news_materials WHERE url = ANY(%s)''',
                    ([s['url'] for s in config['sources']],))
        cached = {row[0]: row for row in cur.fetchall()}
    for number, item in enumerate(config['sources'], 1):
        sid = f'source_{number:02d}'
        row = cached.get(item['url'])
        kind = source_type(item)
        if row is None or row[1] != kind:
            print(f'[{sid}] 数据库未命中，使用现有预处理流程', flush=True)
            continue
        _, _, title, publisher, language, published, content = row
        transcript = content.get('transcript', {})
        valid = (isinstance(content.get('text'), str) and bool(content['text'].strip())) if kind == 'article' else (
            isinstance(transcript, dict) and isinstance(transcript.get('utterances'), list)
            and bool(transcript['utterances']) and all(
                isinstance(r, dict) and isinstance(r.get('text'), str)
                and isinstance(r.get('start_time'), (int, float))
                and isinstance(r.get('end_time'), (int, float))
                and isinstance(r.get('attribute'), dict)
                for r in transcript['utterances']))
        if not valid or (kind == 'video' and language and item.get('asr_language', 'en-US') != language):
            print(f'[{sid}] 数据库内容不完整或语言不同，重新预处理', flush=True)
            continue
        paths = ProjectPaths(Path(root) / 'sources' / sid)
        context = {'title': title, 'channel': publisher,
                   'published_at': published.isoformat() if published else None,
                   'webpage_url': item['url']}
        if kind == 'article':
            save({**item, 'source_id': sid, 'source_type': kind, 'title': title,
                  'publisher': publisher, 'published_at': context['published_at'],
                  'content': content['text']}, paths.root / 'article.json')
            (paths.root / 'article.txt').write_text(content['text'], encoding='utf-8')
            (paths.root / '.download.done').touch()
        else:
            save(transcript, paths.subtitles['json'])
            save(context, paths.root / 'database_context.json')
            for stage in stages:
                (paths.root / f'.{stage}.done').touch()
        (paths.root / '.database.done').touch()
        print(f'[{sid}] 数据库命中，已恢复{ "文章正文" if kind == "article" else "整合及人物识别后的字幕" }', flush=True)


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
    with connect() as conn:
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
