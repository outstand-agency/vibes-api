import io
import json
import os
import unittest
from unittest.mock import patch

from vibes import Vibes


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class VibesTest(unittest.TestCase):
    @patch("vibes.urlopen")
    def test_generate_builds_observed_request_flow(self, open_url):
        open_url.side_effect = [
            Response(b'{"batch":null}'),
            Response(b'{"success":true,"needsPolling":true}'),
        ]
        batch_id, result = Vibes("secret").generate_videos(
            "project-1", "a dancing cat", 2, "720p"
        )
        first, second = (call.args[0] for call in open_url.call_args_list)
        body = json.loads(second.data)

        self.assertEqual(first.full_url, "https://vibes.ai/api/generation-batches")
        self.assertEqual(second.full_url, "https://vibes.ai/api/generate/videos")
        self.assertEqual(body["batchId"], batch_id)
        self.assertEqual(len(body["inputs"]), 2)
        self.assertEqual(body["config"]["generationType"], "t2v")
        self.assertEqual(body["config"]["resolution"], "720p")
        self.assertTrue(result["needsPolling"])

    @patch("vibes.urlopen")
    def test_stream_parses_sse(self, open_url):
        open_url.return_value = Response(
            b'event: update\ndata: {"isComplete":false}\n\n'
            b'data: {"isComplete":true,"videoUrl":"https://example/video.mp4"}\n\n'
        )

        events = list(Vibes("secret").stream_batch("batch-1"))

        self.assertEqual(events[0]["event"], "update")
        self.assertFalse(events[0]["data"]["isComplete"])
        self.assertTrue(events[1]["data"]["isComplete"])

    @patch("vibes.urlopen")
    def test_frames_builds_image_input_payload(self, open_url):
        open_url.side_effect = [
            Response(b'{"batch":null}'),
            Response(b'{"success":true,"needsPolling":true}'),
        ]
        start = {"cdnUrl": "https://cdn/start", "mediaEntId": "111", "asset_id": "A1"}
        end = {"cdnUrl": "https://cdn/end", "mediaEntId": "222", "asset_id": "A2"}
        batch_id, _ = Vibes("secret").generate_frames(
            "project-1", "smooth animate", start, end, 2, "720p"
        )
        _, second = (call.args[0] for call in open_url.call_args_list)
        body = json.loads(second.data)
        sources = body["config"]["sourceContentItemIds"]
        self.assertEqual(sources, [
            {"id": "A1", "source": "start_frame"},
            {"id": "A2", "source": "end_frame"},
        ])
        self.assertEqual(body["config"]["directPromptImageHandle"]["image_ent_id"], "111")
        self.assertEqual(body["config"]["lastFrameImageEntId"], "222")
        self.assertEqual(body["inputs"][0]["type"], "image")
        self.assertEqual(body["inputs"][0]["imageUrl"], "https://cdn/start")

    @patch("vibes.urlopen")
    def test_upload_media_multipart(self, open_url):
        open_url.return_value = Response(b'{"mediaEntId":"999"}')
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            handle.write(b"\x89PNG\r\n\x1a\nfake")
            path = handle.name
        try:
            result = Vibes("secret").upload_media(path)
        finally:
            os.unlink(path)
        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, "https://vibes.ai/api/upload-media")
        self.assertTrue(request.headers["Content-type"].startswith("multipart/form-data"))
        self.assertIn(b'filename="', request.data)
        self.assertEqual(result["mediaEntId"], "999")

    @patch("vibes.urlopen")
    def test_upload_media_sets_project_referer(self, open_url):
        open_url.return_value = Response(b'{"mediaEntId":"999"}')
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            handle.write(b"\x89PNG\r\n\x1a\nfake")
            path = handle.name
        try:
            Vibes("secret").upload_media(path, project_id="proj-1")
        finally:
            os.unlink(path)
        request = open_url.call_args.args[0]
        self.assertEqual(
            request.headers.get("Referer"), "https://vibes.ai/projects/proj-1"
        )


if __name__ == "__main__":
    unittest.main()
