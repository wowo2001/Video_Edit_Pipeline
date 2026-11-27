import copy
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from core.path import ProjectPaths
from main import load_batch
import main as main_entry
from pipeline.source_preprocess import (
    SourceGeometryError, check_geometry, default_profile, output_size,
    pixel_box, prepare_episode, save_json, validate_profile,
)


class SourcePreprocessTests(unittest.TestCase):
    def setUp(self):
        self.info = dict(width=1280, height=720, fps="25/1", duration=10, has_audio=True)
        self.profile = default_profile(self.info, "测试电视剧")

    def test_coordinates_apply_to_other_resolutions(self):
        self.assertEqual(pixel_box(self.profile["crop"], 1280, 720), (160, 0, 960, 720))
        self.assertEqual(pixel_box(self.profile["crop"], 1920, 1080), (240, 0, 1440, 1080))
        check_geometry(dict(self.info, width=1920, height=1080), self.profile)

    def test_wrong_aspect_is_skipped_instead_of_misapplying_mask(self):
        with self.assertRaises(SourceGeometryError):
            check_geometry(dict(self.info, width=960), self.profile)

    def test_smaller_parts_are_not_upscaled(self):
        small = dict(self.info, width=640, height=360)
        self.assertEqual(output_size(self.profile, [self.info, small]), (480, 360))

    def test_rejects_out_of_bounds_and_tiny_regions(self):
        for box in (dict(x=.9, y=0, width=.2, height=.2),
                    dict(x=0, y=0, width=.0001, height=.1),
                    dict(x=float("nan"), y=0, width=.2, height=.2)):
            profile = copy.deepcopy(self.profile)
            profile["blur_regions"] = [box]
            with self.assertRaises(ValueError):
                validate_profile(profile)

    def test_skip_blur_is_explicit_empty_list_and_valid(self):
        self.assertEqual(validate_profile(self.profile)["blur_regions"], [])

    def test_batch_rejects_mixed_dramas_before_download(self):
        with tempfile.TemporaryDirectory() as directory:
            tasks = Path(directory)/"tasks.json"
            save_json(tasks, [dict(title="剧一", episode=1, urls="https://example/a"),
                              dict(title="剧二", episode=2, urls="https://example/b")])
            with self.assertRaisesRegex(ValueError, "同一部电视剧"):
                load_batch(tasks)

    @patch("pipeline.source_preprocess.run_cmd")
    @patch("pipeline.source_preprocess.encode_master")
    @patch("pipeline.source_preprocess.probe_source")
    @patch("pipeline.source_preprocess.download_raw_video")
    def test_master_cache_reuses_only_matching_recipe(self, download, probe, encode, run):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root/"raw.mp4"
            raw.write_bytes(b"raw")
            paths = ProjectPaths(root/"episode")
            download.return_value = raw
            probe.return_value = self.info

            def fake_encode(source, destination, *_args):
                Path(destination).write_bytes(b"encoded")
                return self.info

            def fake_concat(command):
                Path(command[-1]).write_bytes(b"master")

            encode.side_effect = fake_encode
            run.side_effect = fake_concat
            first = prepare_episode("https://example/a", paths, self.profile)
            second = prepare_episode("https://example/a", paths, self.profile)
            self.assertEqual(encode.call_count, 1)
            self.assertEqual(first, second)
            captions_changed = copy.deepcopy(self.profile)
            captions_changed["caption_layout"]["width"] = 600
            captions_changed["overlay_layout"]["title"]["y"] = 250
            captions_changed["overlay_layout"]["popup"]["font_size"] = 60
            prepare_episode("https://example/a", paths, captions_changed)
            self.assertEqual(encode.call_count, 1, "字幕布局变化不应重压整集母版")
            command = run.call_args.args[0]
            self.assertEqual(command[command.index("-c")+1], "copy")
            changed = copy.deepcopy(self.profile)
            changed["crf"] = 22
            third = prepare_episode("https://example/a", paths, changed)
            self.assertEqual(encode.call_count, 2)
            self.assertNotEqual(first["main"]["source_master"]["fingerprint"],
                                third["main"]["source_master"]["fingerprint"])

    def test_ui_preview_and_save_use_selected_overlay_layout(self):
        import json
        import threading
        from urllib.request import Request, urlopen
        from pipeline.preprocess_ui import selection_server
        from pipeline.source_preprocess import load_json

        with tempfile.TemporaryDirectory() as directory, \
                patch('pipeline.preprocess_ui.probe_source', return_value=self.info), \
                patch('pipeline.preprocess_ui.encode_master'), \
                patch('pipeline.preprocess_ui.render_final_video') as render:
            path = Path(directory)/'profile.json'
            (Path(directory)/'preview').mkdir()
            server, state = selection_server(Path(directory)/'source.mp4', '测试电视剧', path)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                profile = copy.deepcopy(self.profile)
                profile['overlay_layout']['popup'] = dict(y=600, font_size=60)
                for endpoint in ('preview', 'save'):
                    url = state['url'].replace('/?token=', f'/api/{endpoint}?token=')
                    request = Request(url, data=json.dumps(profile).encode(),
                                      headers={'Content-Type': 'application/json'})
                    with urlopen(request, timeout=5) as response:
                        self.assertTrue(json.load(response)['ok'])
                self.assertEqual(render.call_args.kwargs['text_layout'], profile['overlay_layout'])
                self.assertEqual(load_json(path)['overlay_layout'], profile['overlay_layout'])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_batch_accepts_out_of_order_episodes_and_rejects_invalid_numbers(self):
        with tempfile.TemporaryDirectory() as directory:
            tasks = Path(directory)/'tasks.json'
            jobs = [dict(title='测试电视剧', episode=i, urls=f'https://example/{i}') for i in (8, 1)]
            save_json(tasks, jobs)
            loaded, _ = load_batch(tasks)
            self.assertEqual([job['episode'] for job in loaded], [8, 1])
            for invalid in (None, 0, -1, True, '1'):
                jobs[0]['episode'] = invalid
                save_json(tasks, jobs)
                with self.assertRaisesRegex(ValueError, 'episode'):
                    load_batch(tasks)
            jobs[0]['episode'] = 1
            save_json(tasks, jobs)
            with self.assertRaisesRegex(ValueError, '重复'):
                load_batch(tasks)

    def test_saved_profile_runs_all_episodes_without_opening_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks, profile = root/"tasks.json", root/"profile.json"
            save_json(tasks, [dict(title="测试电视剧", episode=1, urls="https://example/1"),
                              dict(title="测试电视剧", episode=2, urls="https://example/2")])
            save_json(profile, self.profile)
            calls = []

            class FakePipeline:
                def __init__(self, paths):
                    pass

                def run(self, **kwargs):
                    calls.append(kwargs)
                    if len(calls) == 1:
                        raise SourceGeometryError("本集画幅不同")

            module = types.SimpleNamespace(AutoVideoPipeline=FakePipeline)
            with patch.dict("sys.modules", {"pipeline.pipeline": module}), \
                    patch("pipeline.preprocess_ui.choose_profile") as choose, \
                    patch("main.ProjectPaths"), patch("main.save_json"), \
                    patch("traceback.print_exc"), patch("builtins.print"):
                result = main_entry.main(["--tasks", str(tasks), "--profile", str(profile)])
            choose.assert_not_called()
            self.assertEqual(result, 1)
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[1]["preprocess_profile"], self.profile)

    def test_new_batch_asks_once_before_running_every_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks, profile = root/"tasks.json", root/"new_profile.json"
            save_json(tasks, [dict(title="测试电视剧", episode=1, urls=["https://example/1"]),
                              dict(title="测试电视剧", episode=2, urls="https://example/2")])
            from unittest.mock import Mock
            pipeline = Mock()
            module = types.SimpleNamespace(AutoVideoPipeline=pipeline)
            with patch.dict("sys.modules", {"pipeline.pipeline": module}), \
                    patch("pipeline.preprocess_ui.choose_profile", return_value=self.profile) as choose, \
                    patch("main.download_raw_video", return_value=root/"raw.mkv") as download, \
                    patch("main.probe_source"), patch("main.ProjectPaths"), \
                    patch("main.save_json"), patch("builtins.print"):
                result = main_entry.main(["--tasks", str(tasks), "--profile", str(profile)])
            self.assertEqual(result, 0)
            choose.assert_called_once()
            download.assert_called_once_with("https://example/1")
            self.assertEqual(pipeline.return_value.run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
