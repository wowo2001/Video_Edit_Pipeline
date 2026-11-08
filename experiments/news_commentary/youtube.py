"""Map finished news assets and AI-generated tags to YouTube upload arguments."""
import math
import subprocess
from pathlib import Path
from core.utils import read_json
from core.path import ProjectPaths

CHANNEL_ID = 'UCGTnz6vvLd3upDsDS0uYwNw'


def build_upload_config(root, orientation='landscape'):
    """Build arguments only; no network requests or uploads."""
    if orientation not in ('portrait', 'landscape'):
        raise ValueError('orientation 必须是 portrait 或 landscape')
    paths = ProjectPaths(Path(root))
    main = read_json(paths.media)['main']
    plan = read_json(paths.root / 'commentary_plan.json')
    tags = plan.get('tags')
    if not isinstance(tags, list) or not tags or any(not isinstance(t, str) or not t.strip() for t in tags):
        raise ValueError('规划中缺少 AI 生成的 tags，请重新运行 plan 或补充经确认的标签')
    landscape = orientation == 'landscape'
    video_key = 'commentary_landscape_video_path' if landscape else 'commentary_news_video_path'
    cover_key = 'commentary_cover_landscape_path' if landscape else 'commentary_cover_path'
    sources = read_json(paths.root / 'source_catalog.json')
    links = '\n'.join(f"{s.get('publisher') or s['source_id']}: {s['url']}" for s in sources)
    return dict(video_path=main[video_key], title=plan['title'], channel_id=CHANNEL_ID,
                thumbnail_path=main[cover_key],
                description=(plan.get('summary', '') + '\n\n素材来源：\n' + links).strip(),
                tags=tags, privacy='public', publish_at=None)


def upload_news_videos(root):
    """Publish both deliverables and retain per-orientation progress on failure."""
    from core.utils import write_json
    from services.youtube_upload import upload_video
    paths = ProjectPaths(Path(root))
    configs = {orientation: build_upload_config(root, orientation)
               for orientation in ('portrait', 'landscape')}
    # Check both deliverables before publishing either one.
    for config in configs.values():
        for key in ('video_path', 'thumbnail_path'):
            path = Path(config[key])
            if not path.is_file() or not path.stat().st_size:
                raise ValueError(f'上传文件缺失或为空: {path}')
    duration = float(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', configs['portrait']['video_path']], text=True))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('无法确认竖屏成片时长，停止 YouTube 上传')
    results = {}
    if duration > 180:
        skipped = dict(status='skipped', reason='duration_exceeds_180_seconds', duration_seconds=duration)
        media = read_json(paths.media)
        media['main'].setdefault('youtube', {})['portrait'] = skipped
        write_json(media, paths.media, ensure_ascii=False, indent=2)
        results['portrait'] = skipped
        del configs['portrait']
        print(f'跳过 YouTube 竖屏视频及封面：成片 {duration:.3f} 秒，超过 180 秒；横屏继续上传', flush=True)
    for orientation, config in configs.items():
        receipt = paths.root / f'youtube_{orientation}.json'
        print(f'YouTube 公开发布 {orientation}: {config["title"]}', flush=True)
        try:
            result = upload_video(**config, receipt_path=receipt, contains_synthetic_media=True)
        except Exception as error:
            media = read_json(paths.media)
            progress = read_json(receipt) if receipt.exists() else {}
            media['main'].setdefault('youtube', {})[orientation] = {
                'status': 'failed', 'video_id': progress.get('video_id'),
                'url': progress.get('url'), 'receipt_path': str(receipt),
                'error': str(error)}
            write_json(media, paths.media, ensure_ascii=False, indent=2)
            raise
        media = read_json(paths.media)
        media['main'].setdefault('youtube', {})[orientation] = {
            'status': 'completed', 'video_id': result['video_id'], 'url': result['url'],
            'receipt_path': str(receipt), 'privacy': 'public', 'tags': config['tags']}
        write_json(media, paths.media, ensure_ascii=False, indent=2)
        results[orientation] = result
        print(f'YouTube {orientation} 视频及封面上传成功: {result["url"]}', flush=True)
    return results
