"""Read public YouTube channel uploads for the news-selection UI."""

from datetime import datetime, timedelta, timezone
import re
from urllib.parse import urlparse

import requests


API_ROOT = "https://www.googleapis.com/youtube/v3"


class YouTubeNews:
    def __init__(self, api_key: str, timeout: int = 30):
        if not api_key:
            raise ValueError("缺少 YOUTUBE_API_KEY")
        self.api_key = api_key
        self.timeout = timeout

    def _get(self, resource: str, **params) -> dict:
        response = requests.get(
            f"{API_ROOT}/{resource}",
            params={"key": self.api_key, **params},
            timeout=self.timeout,
        )
        if not response.ok:
            try:
                message = response.json()["error"]["message"]
            except (ValueError, KeyError):
                message = response.text
            raise RuntimeError(f"YouTube API 请求失败 ({response.status_code}): {message}")
        return response.json()

    @staticmethod
    def _channel_filter(channel_ref: str) -> dict:
        value = channel_ref.strip()
        if re.fullmatch(r"UC[\w-]{20,}", value):
            return {"id": value}
        if value.startswith("@"):
            return {"forHandle": value}

        parsed = urlparse(value if "://" in value else f"https://{value}")
        channel_match = re.search(r"/channel/(UC[\w-]+)", parsed.path)
        if channel_match:
            return {"id": channel_match.group(1)}
        handle_match = re.search(r"/@([^/?]+)", parsed.path)
        if handle_match:
            return {"forHandle": f"@{handle_match.group(1)}"}
        raise ValueError("频道引用必须是 YouTube 频道网址、@handle 或 UC 开头的 Channel ID")

    def resolve_channel(self, channel_ref: str) -> dict:
        result = self._get(
            "channels",
            part="snippet,contentDetails",
            **self._channel_filter(channel_ref),
        )
        items = result.get("items", [])
        if not items:
            raise ValueError(f"找不到 YouTube 频道: {channel_ref}")
        channel = items[0]
        return {
            "channel_id": channel["id"],
            "channel_name": channel["snippet"]["title"],
            "uploads_playlist_id": channel["contentDetails"]["relatedPlaylists"]["uploads"],
        }

    def recent_videos(self, source: dict, days: int) -> list[dict]:
        channel = self.resolve_channel(source["channel_ref"])
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        page_token = None
        videos = []

        while True:
            result = self._get(
                "playlistItems",
                part="snippet,contentDetails",
                playlistId=channel["uploads_playlist_id"],
                maxResults=50,
                pageToken=page_token,
            )
            for item in result.get("items", []):
                snippet = item.get("snippet", {})
                resource = snippet.get("resourceId", {})
                if resource.get("kind") != "youtube#video":
                    continue
                published_at = datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00"))
                if published_at < cutoff:
                    return videos
                video_id = resource["videoId"]
                videos.append({
                    "source_name": source["name"],
                    "channel_id": channel["channel_id"],
                    "channel_name": channel["channel_name"],
                    "title": snippet["title"],
                    "published_at": published_at.isoformat(),
                    "video_id": video_id,
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "thumbnail_url": snippet.get("thumbnails", {}).get("medium", {}).get("url"),
                })
            page_token = result.get("nextPageToken")
            if not page_token:
                return videos
