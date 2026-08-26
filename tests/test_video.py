import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline.video import cut_video_range, fit_forward_video_range


class VideoCutTests(unittest.TestCase):
    def test_background_range_starts_at_visual_anchor(self):
        self.assertEqual(fit_forward_video_range(12, 8, 100), (12, 20))

    def test_background_range_shifts_back_at_end_without_shortening(self):
        self.assertEqual(fit_forward_video_range(96, 8, 100), (92, 100))

    def test_background_range_rejects_audio_longer_than_source(self):
        with self.assertRaisesRegex(ValueError, "无法承载"):
            fit_forward_video_range(0, 8, 5)

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
