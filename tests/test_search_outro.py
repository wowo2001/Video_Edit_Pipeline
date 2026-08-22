import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.utils import read_json, write_json
from search import SearchPipeline


class SearchOutroTests(unittest.TestCase):
    @patch("search.get_duration")
    def test_question_outro_requires_enough_source_video(self, get_duration):
        get_duration.return_value = 2522.689

        has_capacity, remaining_duration = SearchPipeline._has_question_outro_capacity(
            "source.mp4",
            dialogue_end=2522.675,
            question_duration=10.272,
        )

        self.assertFalse(has_capacity)
        self.assertAlmostEqual(remaining_duration, 0.014, places=3)

    def test_final_segment_mixes_question_after_existing_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = SimpleNamespace(
                media=root / "media.json",
                scene_selected_subtitle=root / "segments.json",
                final_clips=root / "final_clips",
                root=root,
            )
            paths.final_clips.mkdir()

            clip_path = root / "clip.mp4"
            narration_path = root / "narration.mp3"
            question_path = root / "question.mp3"
            question_clip_path = root / "question_clip.mp4"
            hook_clip_path = root / "hook.mp4"
            hook_audio_path = root / "hook.mp3"
            for path in (
                clip_path,
                narration_path,
                question_path,
                question_clip_path,
                hook_clip_path,
                hook_audio_path,
            ):
                path.touch()

            write_json(
                [{"scene_id": 7, "segments": [{"segment_id": 1}]}],
                paths.scene_selected_subtitle,
            )
            write_json(
                {
                    "search": {
                        "scenes": {
                            "7": {
                                "segments": {
                                    "1": {
                                        "clip_video_path": str(clip_path),
                                        "narration_audio_path": str(narration_path),
                                        "audience_question_audio_path": str(question_path),
                                        "audience_question_video_path": str(question_clip_path),
                                    }
                                }
                            }
                        },
                        "hook": {
                            "clip_video_path": str(hook_clip_path),
                            "narration_audio_path": str(hook_audio_path),
                        },
                    }
                },
                paths.media,
            )
            pipeline = SearchPipeline.__new__(SearchPipeline)
            pipeline.paths = paths

            def fake_mix(video_path, audio_path, output_path, alignment="start"):
                Path(output_path).touch()

            def fake_concat(video_paths, output_path, _list_path):
                Path(output_path).touch()

            with (
                patch("search.mix_narration_audio", side_effect=fake_mix) as mix_audio,
                patch("search.concat_video_paths", side_effect=fake_concat) as concat_videos,
            ):
                pipeline._mix_audio()

            first_call, second_call = mix_audio.call_args_list[:2]
            intermediate_path = paths.final_clips / "scene_7_segment_1_narration.mp4"
            question_mix_path = paths.final_clips / "scene_7_segment_1_question.mp4"
            final_path = paths.final_clips / "scene_7_segment_1_final.mp4"
            self.assertEqual(first_call.args, (clip_path, narration_path, intermediate_path))
            self.assertEqual(second_call.args, (question_clip_path, question_path, question_mix_path))
            self.assertEqual(second_call.kwargs, {})
            self.assertEqual(
                concat_videos.call_args.args[:2],
                ([intermediate_path, question_mix_path], final_path),
            )
            self.assertFalse(intermediate_path.exists())
            self.assertFalse(question_mix_path.exists())
            self.assertEqual(
                read_json(paths.media)["search"]["scenes"]["7"]["segments"]["1"][
                    "final_video_path"
                ],
                str(final_path),
            )


if __name__ == "__main__":
    unittest.main()
