"""Reuse classifications within a caller-owned session dictionary."""
import hashlib
import json

def classify_cached(videos, topics, classify, cache):
    results, missing, paths = {}, [], {}
    for video in videos:
        payload = json.dumps({'video': video, 'topics': topics}, ensure_ascii=False, sort_keys=True)
        path = hashlib.sha256(payload.encode()).hexdigest()
        paths[video['video_id']] = path
        try:
            results[video['video_id']] = cache[path]
        except KeyError:
            missing.append(video)
    if missing:
        returned = {r['video_id']: r for r in classify(missing, topics)
                    if isinstance(r, dict) and isinstance(r.get('video_id'), str)}
        for video in missing:
            vid = video['video_id']
            result = returned.get(vid, {'video_id': vid, 'relevant': False,
                                       'matched_topics': [], 'reason': '模型未返回该视频的分类结果'})
            # Missing results stay cached too; viewing another topic must not trigger retries.
            results[vid] = result
            cache[paths[vid]] = result
    return [results[v['video_id']] for v in videos]
