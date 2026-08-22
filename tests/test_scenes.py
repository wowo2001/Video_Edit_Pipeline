import tempfile
import unittest
from pathlib import Path

from core.utils import read_json, write_json
from pipeline.scenes import (
    attach_subtitles_to_segments,
    attach_subtitles_to_selected_scenes,
)


class FakePostgresClient:
    def get_subtitles_by_scene_id(self, scene_id):
        if scene_id != 7:
            raise AssertionError(f"unexpected scene_id: {scene_id}")
        return [
            (1000, 3400, "第一句", "甲"),
            (5000, 6800, "第二句", "乙"),
        ]


class ScenePlanningTests(unittest.TestCase):
    def test_scene_plan_keeps_budget_and_adds_subtitle_durations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            selected_path = root / "selected.json"
            scenes_path = root / "scenes.json"
            output_path = root / "with_subtitles.json"
            write_json(
                [{
                    "scene_id": 7,
                    "task": "只保留冲突",
                    "max_segments": 2,
                    "target_duration_seconds": 55,
                    "audience_question": "这句话是否值得讨论？",
                }],
                selected_path,
            )
            write_json(
                [{"scene_id": 7, "title": "测试", "summary": "测试场景"}],
                scenes_path,
            )

            attach_subtitles_to_selected_scenes(
                selected_path,
                scenes_path,
                output_path,
                FakePostgresClient(),
            )

            scene = read_json(output_path)[0]
            self.assertEqual(scene["max_segments"], 2)
            self.assertEqual(scene["target_duration_seconds"], 55)
            self.assertEqual(scene["audience_question"], "这句话是否值得讨论？")
            self.assertIn("[1 | 2.4秒] 甲：第一句", scene["subtitles_plain_text"])
            self.assertIn("[2 | 1.8秒] 乙：第二句", scene["subtitles_plain_text"])

    def test_attached_segment_records_actual_dialogue_duration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scenes_path = root / "scenes.json"
            plans_path = root / "plans.json"
            output_path = root / "output.json"
            write_json(
                [{
                    "scene_id": 7,
                    "subtitles": [
                        {"start_time": 1000, "end_time": 3400, "content": "第一句"},
                        {"start_time": 5000, "end_time": 6800, "content": "第二句"},
                    ],
                }],
                scenes_path,
            )
            write_json(
                [{
                    "scene_id": 7,
                    "segments": [{
                        "segment_id": 1,
                        "narration": "旁白",
                        "subtitle_ids": [1, 2],
                    }],
                }],
                plans_path,
            )

            attach_subtitles_to_segments(scenes_path, plans_path, output_path)

            segment = read_json(output_path)[0]["segments"][0]
            self.assertEqual(segment["dialogue_duration_seconds"], 4.2)
            self.assertNotIn("subtitle_ids", segment)


if __name__ == "__main__":
    unittest.main()
