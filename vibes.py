#!/usr/bin/env python3
"""Minimal unofficial client for the private vibes.ai web API."""

import argparse
import json
import mimetypes
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen


BASE_URL = "https://vibes.ai"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Vibes:
    def __init__(self, session, base_url=BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Cookie": f"cookie_ack=true; meta_session={session}",
            "Origin": self.base_url,
            "User-Agent": "vibes-unofficial-python/0.1",
        }

    def request(self, method, path, body=None, timeout=120):
        data = json.dumps(body, separators=(",", ":")).encode() if body is not None else None
        request = Request(self.base_url + path, data=data, headers=self.headers, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except HTTPError as error:
            detail = error.read().decode(errors="replace")
            raise RuntimeError(f"{method} {path}: HTTP {error.code}: {detail}") from error
        return json.loads(raw) if raw else None

    def upload_media(self, path, timeout=120):
        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex[:16]}"
        filename = os.path.basename(path)
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        with open(path, "rb") as handle:
            payload = handle.read()
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode()
        tail = f"\r\n--{boundary}--\r\n".encode()
        body = head + payload + tail
        request = Request(
            f"{self.base_url}/api/upload-media",
            data=body,
            headers={
                "Accept": "application/json",
                "Cookie": self.headers["Cookie"],
                "Origin": self.base_url,
                "User-Agent": self.headers["User-Agent"],
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except HTTPError as error:
            detail = error.read().decode(errors="replace")
            raise RuntimeError(f"POST /api/upload-media: HTTP {error.code}: {detail}") from error
        return json.loads(raw) if raw else None

    def project_assets(self, project_id, limit=50, offset=0, timeout=120):
        path = f"/api/project-assets?limit={limit}&offset={offset}&project_id={project_id}"
        headers = {k: v for k, v in self.headers.items() if k != "Content-Type"}
        request = Request(self.base_url + path, headers=headers)
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except HTTPError as error:
            detail = error.read().decode(errors="replace")
            raise RuntimeError(f"GET /api/project-assets: HTTP {error.code}: {detail}") from error
        return json.loads(raw) if raw else None

    def me(self):
        return self.request("GET", "/api/auth/check-token")

    def create_project(self, name="Untitled"):
        return self.request("POST", "/api/projects", {"name": name})

    def create_batch(self, project_id, prompt, count=4, resolution="480p"):
        batch_id = f"batch-{uuid.uuid4()}"
        timestamp = now()
        config = {
            "directGeneration": True,
            "promptModel": "gemini-2.5-flash",
            "aspectRatio": "9:16",
            "imageModel": "midjen-base",
            "videoModel": "midjen-short",
            "resolution": resolution,
            "batchVariation": True,
        }
        body = {
            "id": batch_id,
            "type": "videos",
            "prompt": prompt,
            "timestamp": timestamp,
            "content": [
                {"id": f"{batch_id}-content-{i}", "type": "videos", "isLoading": True}
                for i in range(count)
            ],
            "isComplete": False,
            "config": config,
            "promptModel": config["promptModel"],
            "imageModel": config["imageModel"],
            "videoModel": config["videoModel"],
            "generationStartTime": timestamp,
            "isDirectGeneration": True,
            "projectId": project_id,
        }
        self.request("POST", "/api/generation-batches", body)
        return batch_id, config

    def generate_videos(self, project_id, prompt, count=4, resolution="480p"):
        batch_id, config = self.create_batch(project_id, prompt, count, resolution)
        item = {
            "type": "prompt",
            "value": prompt,
            "original_prompt": prompt,
            "config": config,
        }
        body = {
            "inputs": [item for _ in range(count)],
            "config": {**config, "generationType": "t2v"},
            "batchId": batch_id,
            "mg_request_id": f"www-{uuid.uuid4()}",
            "projectId": project_id,
        }
        return batch_id, self.request("POST", "/api/generate/videos", body)

    def create_frame_batch(self, project_id, prompt, start, end, count=4, resolution="720p"):
        batch_id = f"batch-{uuid.uuid4()}"
        timestamp = now()
        config = {
            "directGeneration": True,
            "promptModel": "gemini-2.5-flash",
            "aspectRatio": "9:16",
            "imageModel": "midjen-base",
            "videoModel": "midjen-short",
            "resolution": resolution,
            "batchVariation": True,
            "sourceContentItemIds": [
                {"id": start["asset_id"], "source": "start_frame"},
                {"id": end["asset_id"], "source": "end_frame"},
            ],
            "directPromptImageHandle": {
                "image_url": start["cdnUrl"],
                "image_ent_id": start["mediaEntId"],
                "source": "asset",
            },
            "lastFrameImageUrl": end["cdnUrl"],
            "lastFrameImageEntId": end["mediaEntId"],
        }
        body = {
            "id": batch_id,
            "type": "videos",
            "prompt": prompt,
            "timestamp": timestamp,
            "content": [
                {"id": f"{batch_id}-content-{i}", "type": "videos", "isLoading": True}
                for i in range(count)
            ],
            "isComplete": False,
            "config": config,
            "promptModel": config["promptModel"],
            "imageModel": config["imageModel"],
            "videoModel": config["videoModel"],
            "generationStartTime": timestamp,
            "isDirectGeneration": True,
            "projectId": project_id,
        }
        self.request("POST", "/api/generation-batches", body)
        return batch_id, config

    def generate_frames(self, project_id, prompt, start, end, count=4, resolution="720p"):
        batch_id, config = self.create_frame_batch(
            project_id, prompt, start, end, count, resolution
        )
        item = {
            "type": "image",
            "imageUrl": start["cdnUrl"],
            "imageEntId": start["mediaEntId"],
            "prompt": prompt,
            "originalPrompt": prompt,
            "config": config,
        }
        body = {
            "inputs": [item for _ in range(count)],
            "config": {**config, "generationType": "t2v"},
            "batchId": batch_id,
            "mg_request_id": f"www-{uuid.uuid4()}",
            "projectId": project_id,
        }
        return batch_id, self.request("POST", "/api/generate/videos", body)

    def find_asset(self, project_id, media_ent_id, retries=5, delay=1.0):
        for _ in range(retries):
            listing = self.project_assets(project_id)
            for item in listing.get("items") or []:
                if item.get("mediaEntId") == media_ent_id:
                    return item
            time.sleep(delay)
        return None

    def stream_batch(self, batch_id):
        headers = {**self.headers, "Accept": "text/event-stream"}
        request = Request(
            f"{self.base_url}/api/generation-batches/{batch_id}/stream",
            headers=headers,
        )
        try:
            with urlopen(request, timeout=610) as response:
                event = {}
                data = []
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if not line:
                        if data:
                            value = "\n".join(data)
                            try:
                                value = json.loads(value)
                            except json.JSONDecodeError:
                                pass
                            yield {**event, "data": value}
                        event, data = {}, []
                    elif line.startswith("data:"):
                        data.append(line[5:].lstrip())
                    elif not line.startswith(":") and ":" in line:
                        key, value = line.split(":", 1)
                        event[key] = value.lstrip()
        except HTTPError as error:
            detail = error.read().decode(errors="replace")
            raise RuntimeError(f"SSE {batch_id}: HTTP {error.code}: {detail}") from error


def client(args):
    session = args.session or os.environ.get("VIBES_META_SESSION")
    if not session:
        raise SystemExit("Set VIBES_META_SESSION to the meta_session cookie value.")
    return Vibes(session, args.base_url)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--session", help="Prefer VIBES_META_SESSION to avoid shell history")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("me")
    project = subparsers.add_parser("project")
    project.add_argument("name", nargs="?", default="Untitled")
    generate = subparsers.add_parser("generate")
    generate.add_argument("prompt")
    generate.add_argument("--project-id")
    generate.add_argument("--count", type=int, default=4, choices=range(1, 5))
    generate.add_argument("--resolution", default="480p", choices=("480p", "720p"))
    generate.add_argument("--no-wait", action="store_true")
    frames = subparsers.add_parser("frames")
    frames.add_argument("start")
    frames.add_argument("end")
    frames.add_argument("prompt")
    frames.add_argument("--project-id")
    frames.add_argument("--count", type=int, default=4, choices=range(1, 5))
    frames.add_argument("--resolution", default="720p", choices=("480p", "720p"))
    frames.add_argument("--no-wait", action="store_true")
    stream = subparsers.add_parser("stream")
    stream.add_argument("batch_id")
    args = parser.parse_args()
    api = client(args)

    if args.command == "me":
        result = api.me()
    elif args.command == "project":
        result = api.create_project(args.name)
    elif args.command == "stream":
        for event in api.stream_batch(args.batch_id):
            print(json.dumps(event, indent=2))
        return
    else:
        project_id = args.project_id
        if not project_id:
            project_id = api.create_project("Untitled")["project"]["id"]
        if args.command == "frames":
            start_upload = api.upload_media(args.start)
            end_upload = api.upload_media(args.end)
            start_asset = api.find_asset(project_id, start_upload["mediaEntId"])
            end_asset = api.find_asset(project_id, end_upload["mediaEntId"])
            if start_asset is None or end_asset is None:
                raise SystemExit("Uploaded frames did not appear in /api/project-assets")
            start = {**start_upload, "asset_id": start_asset["id"]}
            end = {**end_upload, "asset_id": end_asset["id"]}
            batch_id, result = api.generate_frames(
                project_id, args.prompt, start, end, args.count, args.resolution
            )
        else:
            batch_id, result = api.generate_videos(
                project_id, args.prompt, args.count, args.resolution
            )
        print(json.dumps({"batchId": batch_id, "response": result}, indent=2))
        if not args.no_wait and result.get("needsPolling"):
            for event in api.stream_batch(batch_id):
                print(json.dumps(event, indent=2))
        return
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
