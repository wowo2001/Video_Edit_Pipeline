import tempfile
import unittest
from pathlib import Path

from core.utils import read_json, write_json
from pipeline.scenes import (
    attach_subtitles_to_segments,
    attach_subtitles_to_selected_scenes,
)
from services.chatgpt import scene_selection_issues, segment_plan_issues


class FakePostgresClient:
    def get_subtitles_by_scene_id(self, scene_id):
        if scene_id != 7:
            raise AssertionError(f"unexpected scene_id: {scene_id}")
        return [
            (1000, 3400, "第一句", "甲"),
            (5000, 6800, "第二句", "乙"),
        ]


class ScenePlanningTests(unittest.TestCase):
    def test_scene_selection_rejects_global_budget_overflow(self):
        candidates = [{"scene_id": 7}, {"scene_id": 8}]
        plan = [
            {"scene_id": 7, "max_segments": 4, "target_duration_seconds": 120},
            {"scene_id": 8, "max_segments": 3, "target_duration_seconds": 100},
        ]

        issues = scene_selection_issues(candidates, plan)

        self.assertTrue(any("超过 6 个上限" in issue for issue in issues))
        self.assertTrue(any("超过 210 秒上限" in issue for issue in issues))

    def test_scene_selection_requires_one_final_audience_question(self):
        candidates = [{"scene_id": 7}, {"scene_id": 8}]
        plan = [
            {"scene_id": 7, "max_segments": 1, "target_duration_seconds": 50},
            {"scene_id": 8, "max_segments": 2, "target_duration_seconds": 100},
        ]

        issues = scene_selection_issues(candidates, plan)

        self.assertIn("最后一个场景必须提供 audience_question", issues)

    def test_segment_plan_rejects_too_much_or_repeated_dialogue(self):
        scene = {
            "max_segments": 2,
            "subtitles": [
                {"start_time": 0, "end_time": 8000},
                {"start_time": 8000, "end_time": 15000},
                {"start_time": 15000, "end_time": 17000},
            ],
        }
        plan = {
            "segments": [
                {"segment_id": 1, "subtitle_ids": [1, 2]},
                {"segment_id": 2, "subtitle_ids": [2, 3]},
                {"segment_id": 3, "subtitle_ids": [3]},
            ]
        }

        issues = segment_plan_issues(scene, plan)

        self.assertTrue(any("超过上限 2" in issue for issue in issues))
        self.assertTrue(any("15.0 秒" in issue for issue in issues))
        self.assertTrue(any("重复使用" in issue for issue in issues))

    def test_segment_plan_rejects_non_contiguous_subtitle_ids(self):
        scene = {
            "max_segments": 1,
            "subtitles": [
                {"start_time": 0, "end_time": 1000},
                {"start_time": 1000, "end_time": 2000},
                {"start_time": 2000, "end_time": 3000},
            ],
        }
        plan = {"segments": [{"segment_id": 1, "subtitle_ids": [1, 3]}]}

        issues = segment_plan_issues(scene, plan)

        self.assertTrue(any("必须连续" in issue for issue in issues))

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
