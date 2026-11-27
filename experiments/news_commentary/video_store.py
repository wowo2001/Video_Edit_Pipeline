"""Archive landscape publications with their plan and final subtitle timeline."""
import re
from pathlib import Path

from psycopg.types.json import Jsonb

from core.utils import read_json
from experiments.news_commentary.material_store import connect


def parse_subtitles(path):
    def milliseconds(stamp):
        h, m, s, ms = map(int, re.split('[:,]', stamp))
        return ((h * 60 + m) * 60 + s) * 1000 + ms

    rows = []
    for block in re.split(r'\n\s*\n', Path(path).read_text(encoding='utf-8-sig').strip()):
        _, timing, text = block.split('\n', 2)
        start, end = timing.split(' --> ')
        rows.append(dict(start_ms=milliseconds(start), end_ms=milliseconds(end), text=text))
    return rows


def store_landscape(root, result, config):
    """Insert once; retries never replace the archived publication."""
    video_id = result['video_id']
    with connect() as conn:
        if conn.execute('SELECT 1 FROM news_videos WHERE video_id = %s', (video_id,)).fetchone():
            return False
        plan = read_json(Path(root) / 'commentary_plan.json')
        subtitles = parse_subtitles(config['caption_path'])
        # Content comes from local files; query only the actual publication date.
        from services.youtube_upload import connect as youtube_connect
        service = youtube_connect('auth/youtube_client.json', 'auth/youtube_token.json')
        video = service.videos().list(part='snippet,status', id=video_id).execute()['items'][0]
        published_at = (video['snippet']['publishedAt']
                        if video['status']['privacyStatus'] == 'public' else None)
        row = conn.execute('''
            INSERT INTO news_videos (video_id, title, plan, subtitles, published_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (video_id) DO NOTHING RETURNING id
        ''', (video_id, config['title'], Jsonb(plan), Jsonb(subtitles), published_at)).fetchone()
    return row is not None
