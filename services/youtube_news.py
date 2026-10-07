"""Read public YouTube channel uploads for the news-selection UI."""

from datetime import datetime, timedelta, timezone
import re
from urllib.parse import urlparse

import requests


API_ROOT = "https://www.googleapis.com/youtube/v3"
ISO_8601_DURATION_PATTERN = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


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
    def _duration_seconds(value: str) -> int | None:
        """Convert a YouTube ISO 8601 duration such as PT1H02M03S to seconds."""
        match = ISO_8601_DURATION_PATTERN.fullmatch(value)
        if not match:
            return None
        parts = match.groupdict(default="0")
        return (
            int(parts["days"]) * 86_400
            + int(parts["hours"]) * 3_600
            + int(parts["minutes"]) * 60
            + int(parts["seconds"])
        )

    def add_video_durations(self, videos: list[dict]) -> list[dict]:
        """Attach duration_seconds to candidate videos in batches of 50 IDs."""
        video_ids = list(dict.fromkeys(
            str(video.get("video_id") or "") for video in videos if video.get("video_id")
        ))
        durations: dict[str, int] = {}
        for start in range(0, len(video_ids), 50):
            result = self._get(
                "videos",
                part="contentDetails",
                id=",".join(video_ids[start:start + 50]),
            )
            for item in result.get("items", []):
                duration = self._duration_seconds(
                    str(item.get("contentDetails", {}).get("duration") or "")
                )
                if duration is not None:
                    durations[str(item.get("id"))] = duration
        for video in videos:
            video["duration_seconds"] = durations.get(str(video.get("video_id")))
        return videos

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
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        playlist_id = source.get("playlist_id")
        if playlist_id:
            return self._recent_playlist_videos(source, str(playlist_id), cutoff)

        channel = self.resolve_channel(source["channel_ref"])
        if source.get("live_streams_only"):
            return self._recent_completed_live_streams(source, channel, cutoff)
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

    def _recent_playlist_videos(
        self, source: dict, playlist_id: str, cutoff: datetime
    ) -> list[dict]:
        """Return recent videos from a user-supplied YouTube playlist."""
        page_token = None
        videos = []
        while True:
            result = self._get(
                "playlistItems",
                part="snippet,contentDetails",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=page_token,
            )
            for item in result.get("items", []):
                snippet = item.get("snippet", {})
                resource = snippet.get("resourceId", {})
                if resource.get("kind") != "youtube#video":
                    continue
                published_value = (
                    item.get("contentDetails", {}).get("videoPublishedAt")
                    or snippet.get("publishedAt")
                )
                if not published_value:
                    continue
                published_at = datetime.fromisoformat(published_value.replace("Z", "+00:00"))
                if published_at < cutoff:
                    continue
                video_id = resource.get("videoId")
                if not video_id:
                    continue
                videos.append({
                    "source_name": source["name"],
                    "channel_id": snippet.get("videoOwnerChannelId", ""),
                    "channel_name": snippet.get("videoOwnerChannelTitle", source["name"]),
                    "title": snippet.get("title", ""),
                    "published_at": published_at.isoformat(),
                    "video_id": video_id,
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "thumbnail_url": snippet.get("thumbnails", {}).get("medium", {}).get("url"),
                })
            page_token = result.get("nextPageToken")
            if not page_token:
                return videos

    def _recent_completed_live_streams(
        self, source: dict, channel: dict, cutoff: datetime
    ) -> list[dict]:
        """Return archived broadcasts shown under a channel's Live tab."""
        page_token = None
        videos = []
        while True:
            result = self._get(
                "search",
                part="snippet",
                channelId=channel["channel_id"],
                eventType="completed",
                type="video",
                order="date",
                publishedAfter=cutoff.isoformat().replace("+00:00", "Z"),
                maxResults=50,
                pageToken=page_token,
            )
            for item in result.get("items", []):
                snippet = item.get("snippet", {})
                video_id = item.get("id", {}).get("videoId")
                if not video_id:
                    continue
                videos.append({
                    "source_name": source["name"],
                    "channel_id": channel["channel_id"],
                    "channel_name": channel["channel_name"],
                    "title": snippet.get("title", ""),
                    "published_at": snippet["publishedAt"],
                    "video_id": video_id,
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "thumbnail_url": snippet.get("thumbnails", {}).get("medium", {}).get("url"),
                })
            page_token = result.get("nextPageToken")
            if not page_token:
                return videos
