import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.utils import write_json
from pipeline.audio import mix_background_music, resolve_background_music


class BackgroundMusicTests(unittest.TestCase):
    def test_resolve_background_music_supports_id_and_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            music_path = root / "music.mp3"
            registry_path = root / "background_music.json"
            music_path.touch()
            write_json(
                [{
                    "id": "test_music",
                    "name": "测试音乐",
                    "path": str(music_path),
                    "default_volume": 0.12,
                }],
                registry_path,
            )

            by_id = resolve_background_music("test_music", registry_path)
            by_name = resolve_background_music("测试音乐", registry_path)

            self.assertEqual(by_id["path"], music_path)
            self.assertEqual(by_name["id"], "test_music")

    @patch("pipeline.audio.run_cmd")
    def test_background_music_command_loops_music_and_preserves_video_duration(self, run_command):
        mix_background_music("video.mp4", "music.mp3", "output.mp4", volume=0.08)

        command = run_command.call_args.args[0]
        self.assertEqual(command[command.index("-stream_loop") + 1], "-1")
        self.assertIn("duration=first", command[command.index("-filter_complex") + 1])
        self.assertEqual(command[command.index("-map") + 1], "0:v")
        self.assertIn("volume=0.08", command[command.index("-filter_complex") + 1])


if __name__ == "__main__":
    unittest.main()
