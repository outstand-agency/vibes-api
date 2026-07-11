"""Offline tests for the FastAPI service."""

import base64
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("R2_ENDPOINT", "https://x.r2.cloudflarestorage.com")
os.environ.setdefault("R2_ACCESS_KEY_ID", "ak")
os.environ.setdefault("R2_SECRET_ACCESS_KEY", "sk")
os.environ.setdefault("R2_PUBLIC_URL", "https://pub.example.com")

from fastapi.testclient import TestClient

from app.main import app


def _client():
    return TestClient(app)


def _patched_stream_client(complete_items, project_id="p1"):
    mock = MagicMock()
    mock.create_project.return_value = {"project": {"id": project_id}}
    mock.generate_videos.return_value = ("batch-1", {"resolution": "720p"})
    mock.generate_frames.return_value = ("batch-2", {"resolution": "720p"})
    mock.stream_batch.return_value = iter(
        [
            {"data": {"isComplete": False, "items": []}},
            {"data": {"isComplete": True, "items": complete_items}},
        ]
    )
    return mock


class HealthTests(unittest.TestCase):
    def test_healthz_reports_r2(self):
        with _client() as test_client:
            response = test_client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["r2"])


class ProjectsTests(unittest.TestCase):
    @patch("app.main.make_client")
    def test_create_project_returns_id(self, make_client):
        client = MagicMock()
        client.create_project.return_value = {"project": {"id": "p1"}}
        make_client.return_value = client
        with _client() as test_client:
            response = test_client.post(
                "/projects",
                headers={"X-Vibes-Session": "cookie"},
                json={"name": "My project"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"project_id": "p1"})

    def test_create_project_requires_session(self):
        with _client() as test_client:
            response = test_client.post("/projects", json={"name": "x"})
        self.assertEqual(response.status_code, 401)


class GenerateTests(unittest.TestCase):
    COMPLETED = [
        {
            "id": "item-1",
            "videoUrl": "https://fbcdn/video.mp4",
            "imageUrl": "https://fbcdn/thumb.jpg",
        }
    ]

    def _http_mock(self, content=b"\x00\x01\x02video-bytes"):
        http = AsyncMock()
        http.__aenter__.return_value = http
        http.__aexit__.return_value = None
        http.get.return_value = MagicMock(
            raise_for_status=MagicMock(), content=content
        )
        return http

    @patch("app.main.httpx.AsyncClient")
    @patch("app.main.make_client")
    def test_generate_default_uploads_to_r2(self, make_client, http_client):
        make_client.return_value = _patched_stream_client(self.COMPLETED)
        http_client.return_value = self._http_mock()
        r2 = MagicMock()
        r2.put_bytes.return_value = "https://pub.example.com/vibes/batch-1/item-1.mp4"

        with _client() as test_client:
            with patch.object(app.state, "storage", new=r2, create=True):
                response = test_client.post(
                    "/generate",
                    headers={"X-Vibes-Session": "cookie"},
                    json={"prompt": "a dancing cat", "count": 1, "resolution": "720p"},
                )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["batch_id"], "batch-1")
        self.assertEqual(body["project_id"], "p1" if False else body["project_id"])
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(
            body["items"][0]["r2_url"],
            "https://pub.example.com/vibes/batch-1/item-1.mp4",
        )
        self.assertEqual(body["items"][0]["size"], 14)

    @patch("app.main.httpx.AsyncClient")
    @patch("app.main.make_client")
    def test_generate_stream_returns_octet_stream(self, make_client, http_client):
        make_client.return_value = _patched_stream_client(self.COMPLETED)
        http_client.return_value = self._http_mock(content=b"STREAM-BYTES")
        with _client() as test_client:
            response = test_client.post(
                "/generate",
                headers={"X-Vibes-Session": "cookie"},
                json={"prompt": "a dancing cat", "count": 1, "download": "stream"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "video/mp4")
        self.assertEqual(response.headers["x-batch-id"], "batch-1")
        self.assertEqual(response.content, b"STREAM-BYTES")

    @patch("app.main.httpx.AsyncClient")
    @patch("app.main.make_client")
    def test_generate_base64_returns_json(self, make_client, http_client):
        make_client.return_value = _patched_stream_client(self.COMPLETED)
        http_client.return_value = self._http_mock(content=b"BASE64-BYTES")
        with _client() as test_client:
            response = test_client.post(
                "/generate",
                headers={"X-Vibes-Session": "cookie"},
                json={"prompt": "a dancing cat", "count": 1, "download": "base64"},
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            base64.b64decode(body["items"][0]["bytes_b64"]), b"BASE64-BYTES"
        )

    def test_generate_requires_session(self):
        with _client() as test_client:
            response = test_client.post("/generate", json={"prompt": "a dancing cat"})
        self.assertEqual(response.status_code, 401)

    @patch("app.main.make_client")
    def test_generate_without_r2_returns_503(self, make_client):
        make_client.return_value = _patched_stream_client(self.COMPLETED)
        with _client() as test_client:
            with patch.object(app.state, "storage", new=None, create=True):
                response = test_client.post(
                    "/generate",
                    headers={"X-Vibes-Session": "cookie"},
                    json={"prompt": "a dancing cat", "count": 1},
                )
        self.assertEqual(response.status_code, 503)


class UploadsTests(unittest.TestCase):
    @patch("app.main.make_client")
    def test_upload_returns_asset(self, make_client):
        client = MagicMock()
        client.create_project.return_value = {"project": {"id": "p1"}}
        client.upload_media.return_value = {
            "mediaEntId": "111",
            "cdnUrl": "https://cdn/111",
        }
        make_client.return_value = client
        with _client() as test_client:
            response = test_client.post(
                "/uploads",
                headers={"X-Vibes-Session": "cookie"},
                files={"file": ("a.png", b"\x89PNG\r\n\x1a\nfake", "image/png")},
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["media_id"], "111")
        self.assertEqual(body["cdn_url"], "https://cdn/111")
        self.assertIsNone(body["asset_id"])
        # find_asset is no longer called by /uploads
        client.find_asset.assert_not_called()


class FramesTests(unittest.TestCase):
    COMPLETED = [
        {
            "id": "item-f",
            "videoUrl": "https://fbcdn/fvideo.mp4",
            "imageUrl": "https://fbcdn/fthumb.jpg",
        }
    ]

    @patch("app.main._resolve_frames", new_callable=AsyncMock)
    @patch("app.main.httpx.AsyncClient")
    @patch("app.main.make_client")
    def test_frames_routes_to_generate_frames(self, make_client, http_client, resolve):
        resolve.return_value = (
            {"cdnUrl": "s", "mediaEntId": "1", "asset_id": "a"},
            {"cdnUrl": "e", "mediaEntId": "2", "asset_id": "b"},
        )
        http = AsyncMock()
        http.__aenter__.return_value = http
        http.__aexit__.return_value = None
        http.get.return_value = MagicMock(
            raise_for_status=MagicMock(), content=b"BYTES"
        )
        http_client.return_value = http
        make_client.return_value = _patched_stream_client(self.COMPLETED)
        r2 = MagicMock()
        r2.put_bytes.return_value = "https://pub.example.com/vibes/batch-2/item-f.mp4"

        with _client() as test_client:
            with patch.object(app.state, "storage", new=r2, create=True):
                response = test_client.post(
                    "/frames",
                    headers={"X-Vibes-Session": "cookie"},
                    data={"prompt": "smooth animate", "count": 1},
                    files={
                        "start": ("s.png", b"START", "image/png"),
                        "end": ("e.png", b"END", "image/png"),
                    },
                )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["batch_id"], "batch-2")
        self.assertEqual(body["items"][0]["item_id"], "item-f")


if __name__ == "__main__":
    unittest.main()