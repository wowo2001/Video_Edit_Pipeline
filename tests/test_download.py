import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline.download import download_scene_videos


class FakeS3Client:
    def __init__(self):
        self.download_calls = []

    def download_file(self, source, destination):
        self.download_calls.append((source, destination))
        Path(destination).write_bytes(b"source")


class SceneDownloadCacheTests(unittest.TestCase):
    @patch("pipeline.download.encode_to_standard")
    def test_scene_download_cache_is_reused_between_tasks(self, encode_to_standard):
        def standardize(source, destination):
            Path(destination).write_bytes(Path(source).read_bytes())

        encode_to_standard.side_effect = standardize
        scenes = [
            {
                "scene_id": 7,
                "video_url": "s3://example-bucket/videos/shared-source.mp4",
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "search_download_cache"
            client = FakeS3Client()

            with patch("builtins.print"):
                first_paths = download_scene_videos(scenes, cache_dir, client)
                second_paths = download_scene_videos(scenes, cache_dir, client)

            self.assertEqual(len(client.download_calls), 1)
            self.assertEqual(encode_to_standard.call_count, 1)
            self.assertEqual(first_paths, second_paths)
            self.assertTrue(Path(first_paths["7"]).is_file())
            self.assertEqual(Path(first_paths["7"]).parent.name, "standard")

    @patch("pipeline.download.encode_to_standard")
    def test_same_s3_filename_from_different_urls_uses_distinct_cache_files(
        self,
        encode_to_standard,
    ):
        def standardize(source, destination):
            Path(destination).write_bytes(Path(source).read_bytes())

        encode_to_standard.side_effect = standardize
        scenes = [
            {"scene_id": 7, "video_url": "s3://example-bucket/a/source.mp4"},
            {"scene_id": 8, "video_url": "s3://example-bucket/b/source.mp4"},
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("builtins.print"):
                paths = download_scene_videos(scenes, Path(temp_dir), FakeS3Client())

        self.assertNotEqual(paths["7"], paths["8"])


if __name__ == "__main__":
    unittest.main()
