from pathlib import Path

class ProjectPaths:

    def __init__(self, root: str = "work"):

        self.root = Path(root)
        self.pickle = Path("token.pickle")
        self.credentials = Path("credentials.json")
        self.task_file = Path("tasks.json")

        self.video = self.root / "video.mp4"
        self.audio = self.root / "audio.mp3"
        self.subtitles = {"srt": self.root / "subtitles.srt", "json": self.root / "subtitles.json"}
        self.final_subtitles = {"srt": self.root / "final_subtitles.srt", "json": self.root / "final_subtitles.json"}

        self.script = self.root / "script.json"

        self.clips = self.root / "clips"
        self.final_clips = self.root / "final_clips"
        self.concatenated_video = self.root / "concatenated_video.mp4"
        self.changed_resolution_video = self.root / "changed_resolution_video.mp4"
        self.speed_up_video = self.root / "speed_up_video.mp4"
        self.masked_video = self.root / "masked_video.mp4"
        self.subtitle_video = self.root / "subtitle_video.mp4"
        self.text_overlay_video = self.root / "text_overlay_video.mp4"
        self.gif_overlay_video = self.root / "gif_overlay_video.mp4"
        self.final_audio = self.root / "final_audio.mp3"

        self.narration_audios = self.root / "narration_audios"

        # 自动创建目录
        self.clips.mkdir(parents=True, exist_ok=True)
        self.final_clips.mkdir(parents=True, exist_ok=True)
        self.narration_audios.mkdir(parents=True, exist_ok=True)