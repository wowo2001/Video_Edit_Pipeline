from pathlib import Path

class ProjectPaths:

    def __init__(self, root: str = "work"):

        self.root = Path(root)
        self.pickle = Path("token.pickle")
        self.credentials = Path("credentials.json")
        self.task_file = Path("tasks.json")

        self.video = self.root / "video.mp4"
        self.origin = self.root / "origin"
        self.audio = self.root / "audio.mp3"
        self.subtitles = {"srt": self.root / "subtitles.srt", "json": self.root / "subtitles.json", "stripped_srt": self.root / "subtitles_stripped.srt", "chunked_srt": self.root / "subtitles_chunked.srt"}
        self.subtitles_to_db = self.root / "subtitles_to_db.json"
        self.speaker_mapping = self.root / "speaker_mapping.json"
        self.final_subtitles = {"srt": self.root / "final_subtitles.srt", "json": self.root / "final_subtitles.json"}
        self.embeddings = self.root / "embedding_records.pkl"
        self.story = self.root / "story.json"

        self.script = self.root / "script.json"
        self.scene = self.root / "scene.json"
        self.scene_candidate = self.root / "scene_candidate.json"
        self.selected_scene = self.root / "selected_scene.json"
        self.scene_with_subtitle = self.root / "scene_with_subtitle.json"
        self.scene_clips = self.root / "scene_clips.json"
        self.scene_segmented_clips = self.root / "scene_segmented_clips.json"
        self.scene_selected_subtitle = self.root / "scene_selected_subtitle.json"
        self.hook = self.root / "hook.json"
        self.scene_narration = self.root / "scene_narration.json"
        self.download = self.root / "download"
        self.story = self.root / "story.json"
        self.candidate_metadata = self.root / "candidate_metadata.json"
        self.vocals_path = Path("separated/htdemucs")

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
        self.origin.mkdir(parents=True, exist_ok=True)