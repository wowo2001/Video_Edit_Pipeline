"""YouTube upload with separate OAuth credentials and a persisted upload receipt.

Run: python -m services.youtube_upload --config youtube_upload.json
"""
import argparse
import hashlib
import json
import mimetypes
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ['https://www.googleapis.com/auth/youtube.upload',
          'https://www.googleapis.com/auth/youtube.readonly',
          'https://www.googleapis.com/auth/youtube.force-ssl']


def save_json(path, data, private=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        if private:
            os.chmod(temporary, 0o600)
        json.dump(data, stream, ensure_ascii=False, indent=2)
    temporary.replace(path)


def connect(client_secrets, token_path):
    """First use opens a browser; subsequent uses refresh the separate JSON token."""
    token_path = Path(token_path)
    creds = Credentials.from_authorized_user_file(str(token_path)) if token_path.exists() else None
    if creds and not creds.has_scopes(SCOPES):
        raise ValueError('YouTube token 缺少权限，请换一个 token_path 重新授权')
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), SCOPES)
            creds = flow.run_local_server(port=0, access_type='offline', prompt='consent')
        save_json(token_path, json.loads(creds.to_json()), private=True)
    return build('youtube', 'v3', credentials=creds, cache_discovery=False)


def channels(service):
    return service.channels().list(part='id,snippet', mine=True).execute().get('items', [])


def metadata(title, description='', privacy='private', tags=None, category_id='25',
             language='zh', made_for_kids=False, contains_synthetic_media=None, publish_at=None):
    if not isinstance(title, str) or not title.strip() or len(title) > 100 or any(c in title for c in '<>'):
        raise ValueError('标题必须为 1–100 字符，不能包含 < >')
    if len(description.encode('utf-8')) > 5000 or any(c in description for c in '<>'):
        raise ValueError('简介不能超过 5000 UTF-8 字节，不能包含 < >')
    if privacy not in ('private', 'unlisted', 'public'):
        raise ValueError('privacy 必须是 private、unlisted 或 public')
    if type(made_for_kids) is not bool or (contains_synthetic_media is not None and type(contains_synthetic_media) is not bool):
        raise ValueError('儿童内容和合成内容声明必须是布尔值')
    if tags is not None and (not isinstance(tags, list) or any(not isinstance(t, str) or not t.strip() for t in tags)):
        raise ValueError('tags 必须是非空字符串组成的数组')
    snippet = dict(title=title, description=description, categoryId=str(category_id), defaultLanguage=language)
    if tags:
        snippet['tags'] = tags
    status = dict(privacyStatus=privacy, selfDeclaredMadeForKids=made_for_kids)
    if contains_synthetic_media is not None:
        status['containsSyntheticMedia'] = contains_synthetic_media
    if publish_at:
        date = datetime.fromisoformat(publish_at.replace('Z', '+00:00'))
        if privacy != 'private' or date.tzinfo is None or date <= datetime.now(timezone.utc):
            raise ValueError('定时发布需 privacy=private，且 publish_at 是带时区的未来时间')
        status['publishAt'] = date.astimezone(timezone.utc).isoformat()
    return dict(snippet=snippet, status=status)


def wait_processed(service, video_id, timeout=600):
    deadline = time.monotonic() + timeout
    while True:
        items = service.videos().list(part='processingDetails,status', id=video_id).execute().get('items', [])
        if items:
            item = items[0]
            processing = item.get('processingDetails', {}).get('processingStatus')
            upload = item.get('status', {}).get('uploadStatus')
            if processing in ('failed', 'terminated') or upload in ('failed', 'rejected', 'deleted'):
                raise RuntimeError(f'YouTube 处理失败: {video_id}, {processing}, {upload}')
            if processing == 'succeeded':
                return
        if time.monotonic() >= deadline:
            raise TimeoutError(f'视频已上传，等待处理超时: {video_id}；原命令重试可继续设置封面')
        time.sleep(10)


def prepare_thumbnail(path):
    """Keep the original cover; make a compact JPEG for upload when needed."""
    from io import BytesIO
    from PIL import Image, ImageOps
    limit = 2_000_000
    if path.stat().st_size < limit:
        return path
    with Image.open(path) as source:
        rgba = ImageOps.exif_transpose(source).convert('RGBA')
        image = Image.new('RGB', rgba.size, 'white')
        image.paste(rgba, mask=rgba.getchannel('A'))
    while True:
        for quality in (95, 90, 85, 80, 70):
            buffer = BytesIO()
            image.save(buffer, format='JPEG', quality=quality, optimize=True)
            if buffer.tell() < limit:
                output = path.with_name(path.stem + '_youtube.jpg')
                output.write_bytes(buffer.getvalue())
                print(f'上传封面压缩: {path.stat().st_size/1024:.0f} KB → '
                      f'{output.stat().st_size/1024:.0f} KB', flush=True)
                return output
        image = image.resize((max(1, image.width*4//5), max(1, image.height*4//5)),
                             Image.Resampling.LANCZOS)


def upload_video(*, video_path, title, channel_id, client_secrets='auth/youtube_client.json',
                 token_path='auth/youtube_token.json', thumbnail_path=None, receipt_path=None,
                 description='', privacy='private', tags=None, category_id='25', language='zh',
                 made_for_kids=False, contains_synthetic_media=None, publish_at=None,
                 notify_subscribers=False, processing_timeout=600, service=None,
                 caption_path=None, caption_language='zh-Hans', caption_name='简体中文'):
    """Upload one video. Reuse a saved video ID when retrying thumbnail processing."""
    video = Path(video_path).resolve()
    if not video.is_file() or not video.stat().st_size:
        raise ValueError(f'视频文件不存在或为空: {video}')
    if not channel_id or type(notify_subscribers) is not bool or processing_timeout <= 0:
        raise ValueError('需提供 channel_id、布尔 notify_subscribers 和正数 processing_timeout')
    body = metadata(title, description, privacy, tags, category_id, language,
                    made_for_kids, contains_synthetic_media, publish_at)
    thumbnail = Path(thumbnail_path).resolve() if thumbnail_path else None
    if thumbnail and (not thumbnail.is_file() or not 0 < thumbnail.stat().st_size <= 50 * 1024 * 1024
                      or thumbnail.suffix.lower() not in ('.jpg', '.jpeg', '.png')):
        raise ValueError('封面需为不超过 50 MB 的非空 PNG/JPEG 文件')
    if thumbnail:
        thumbnail = prepare_thumbnail(thumbnail)
    caption = Path(caption_path).resolve() if caption_path else None
    if caption and (not caption.is_file() or not 0 < caption.stat().st_size <= 100 * 1024 * 1024):
        raise ValueError('字幕文件缺失、为空或超过100 MB')
    receipt = Path(receipt_path) if receipt_path else video.with_suffix('.youtube.json')
    digest = hashlib.sha256()
    with video.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    identity = dict(sha256=digest.hexdigest(), channel_id=channel_id, metadata=body,
                    notify_subscribers=notify_subscribers)
    state = json.loads(receipt.read_text()) if receipt.exists() else None
    if state and state.get('request') != identity:
        raise ValueError('上传记录与当前视频/参数不一致；如要新上传，请使用新的 receipt_path')
    if state and not state.get('video_id'):
        raise RuntimeError('上次上传结果未确认；请先在 YouTube Studio 核对，避免重复上传。记录：'+str(receipt))
    service = service or connect(client_secrets, token_path)
    owned = channels(service)
    if len(owned) != 1 or owned[0]['id'] != channel_id:
        raise ValueError('授权频道与 channel_id 不一致，请用对应频道重新授权')
    if not state:
        state = dict(request=identity, status='uploading')
        save_json(receipt, state)
        request = service.videos().insert(part='snippet,status', body=body,
            notifySubscribers=notify_subscribers,
            media_body=MediaFileUpload(str(video), mimetype=mimetypes.guess_type(str(video))[0] or 'application/octet-stream',
                                      chunksize=8*1024*1024, resumable=True))
        response = None
        while response is None:
            progress, response = request.next_chunk(num_retries=5)
            if progress:
                print(f'上传进度: {progress.progress():.0%}', flush=True)
        state.update(video_id=response['id'], url='https://www.youtube.com/watch?v='+response['id'], status='uploaded')
        save_json(receipt, state)
    if thumbnail:
        thumbnail_hash = hashlib.sha256(thumbnail.read_bytes()).hexdigest()
        if state.get('thumbnail_sha256') != thumbnail_hash:
            wait_processed(service, state['video_id'], processing_timeout)
            service.thumbnails().set(videoId=state['video_id'], media_body=MediaFileUpload(
                str(thumbnail), mimetype=mimetypes.guess_type(str(thumbnail))[0])).execute(num_retries=3)
            state.update(thumbnail_sha256=thumbnail_hash, thumbnail_path=str(thumbnail))
            save_json(receipt, state)
    if caption:
        upload_caption(service, state, receipt, caption, caption_language, caption_name)
    return state


def upload_caption(service, state, receipt, path, language, name):
    identity = dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), language=language, name=name)
    if state.get('caption', {}).get('request') == identity:
        return
    # Recover an insert that succeeded remotely even if saving the receipt failed.
    tracks = service.captions().list(part='snippet', videoId=state['video_id']).execute(num_retries=3)
    existing = next((t for t in tracks.get('items', [])
                     if t['snippet']['language'] == language and t['snippet']['name'] == name), None)
    media = MediaFileUpload(str(path), mimetype='application/octet-stream')
    if existing:
        request = service.captions().update(part='snippet',
            body={'id': existing['id'], 'snippet': {'isDraft': False}}, media_body=media)
    else:
        request = service.captions().insert(part='snippet', body={'snippet': {
            'videoId': state['video_id'], 'language': language, 'name': name, 'isDraft': False}}, media_body=media)
    result = request.execute(num_retries=3)
    state['caption'] = {'id': result['id'], 'request': identity, 'path': str(path)}
    save_json(receipt, state)
    print('YouTube 中文字幕轨道上传成功', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, help='上传参数 JSON（路径相对当前工作目录）')
    parser.add_argument('--channels', action='store_true', help='仅授权并显示当前频道，不上传')
    parser.add_argument('--client-secrets', default='auth/youtube_client.json')
    parser.add_argument('--token-path', default='auth/youtube_token.json')
    args = parser.parse_args()
    if args.channels:
        result = [dict(id=c['id'], title=c['snippet']['title']) for c in channels(connect(args.client_secrets, args.token_path))]
    elif args.config:
        result = upload_video(**json.loads(args.config.read_text(encoding='utf-8')))
    else:
        parser.error('请提供 --config 或 --channels')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
