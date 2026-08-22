import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline.video import cut_video_range


class VideoCutTests(unittest.TestCase):
    @patch("pipeline.video.concat_videos_ffmpeg")
    @patch("pipeline.video.cut_video_ffmpeg")
    def test_question_range_starts_after_the_original_dialogue(
        self,
        cut_video_ffmpeg,
        _concat_videos_ffmpeg,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "question.mp4"
            cut_video_range(
                "source.mp4",
                output_path,
                start=12,
                end=15,
            )

            _, _, start, end = cut_video_ffmpeg.call_args.args
            self.assertEqual(start, 12)
            self.assertEqual(end, 15)


if __name__ == "__main__":
    unittest.main()
