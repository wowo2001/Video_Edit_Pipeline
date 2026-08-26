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

    def test_background_segment_cuts_forward_for_exact_narration_duration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = SimpleNamespace(
                media=root / "media.json",
                scene_selected_subtitle=root / "segments.json",
                clips=root / "clips",
                hook=root / "hook.json",
            )
            paths.clips.mkdir()
            source_path = root / "source.mp4"
            source_path.touch()
            write_json(
                [{
                    "scene_id": 7,
                    "segments": [{
                        "segment_id": 1,
                        "type": "narration_only",
                        "narration_length": 5000,
                        "visual_subtitles": [
                            {"start_time": 10000, "end_time": 12000}
                        ],
                    }],
                }],
                paths.scene_selected_subtitle,
            )
            write_json(
                {
                    "scene_id": 7,
                    "subtitles": [{"start_time": 1000, "end_time": 2000}],
                    "hook_length": 1000,
                },
                paths.hook,
            )
            write_json(
                {
                    "search": {
                        "scenes": {
                            "7": {
                                "source_video_path": str(source_path),
                                "segments": {"1": {}},
                            }
                        },
                        "hook": {},
                    }
                },
                paths.media,
            )
            pipeline = SearchPipeline.__new__(SearchPipeline)
            pipeline.paths = paths

            def fake_cut_range(_input, output, _start, _end):
                Path(output).touch()
                return Path(output)

            def fake_cut_video(_input, _subtitles, _duration, output, **_kwargs):
                Path(output).touch()
                return Path(output)

            with (
                patch("search.get_duration", return_value=100),
                patch("search.cut_video_range", side_effect=fake_cut_range) as cut_range,
                patch("search.cut_video", side_effect=fake_cut_video),
            ):
                pipeline._cut_videos()

            background_output = paths.clips / "scene_7_segment_1.mp4"
            self.assertEqual(
                cut_range.call_args.args,
                (source_path, background_output, 10.0, 15.0),
            )
            segment_media = read_json(paths.media)["search"]["scenes"]["7"][
                "segments"
            ]["1"]
            self.assertEqual(segment_media["type"], "narration_only")
            self.assertEqual(
                segment_media["narration_visual_range"],
                {"start": 10.0, "end": 15.0},
            )

    def test_background_segment_ducks_original_audio_under_narration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = SimpleNamespace(
                media=root / "media.json",
                scene_selected_subtitle=root / "segments.json",
                final_clips=root / "final_clips",
            )
            paths.final_clips.mkdir()
            clip_path = root / "background_clip.mp4"
            narration_path = root / "narration.mp3"
            hook_clip_path = root / "hook.mp4"
            hook_audio_path = root / "hook.mp3"
            for path in (
                clip_path,
                narration_path,
                hook_clip_path,
                hook_audio_path,
            ):
                path.touch()
            write_json(
                [{
                    "scene_id": 7,
                    "segments": [{"segment_id": 1, "type": "narration_only"}],
                }],
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

            def fake_background_mix(video_path, audio_path, output_path):
                Path(output_path).touch()

            with (
                patch(
                    "search.mix_background_narration_audio",
                    side_effect=fake_background_mix,
                ) as background_mix,
                patch("search.mix_narration_audio", side_effect=fake_mix) as mix_audio,
            ):
                pipeline._mix_audio()

            output_path = paths.final_clips / "scene_7_segment_1_final.mp4"
            self.assertEqual(
                background_mix.call_args.args,
                (clip_path, narration_path, output_path),
            )
            self.assertEqual(mix_audio.call_count, 1)
            self.assertEqual(
                mix_audio.call_args.kwargs,
                {"alignment": "end"},
            )


if __name__ == "__main__":
    unittest.main()
