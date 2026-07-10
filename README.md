# vibes-api

Unofficial FastAPI wrapper around the private **vibes.ai** video-generation API, with Cloudflare R2 as the storage backend.

> ⚠️ **Unofficial.** This is reverse-engineered from the vibes.ai web client. Cookies expire, payloads change, and Meta can rate-limit or block the requests at any time. Each generated video consumes your personal vibes.ai quota.

## Architecture

```
You ──HTTP──▶ Render (FastAPI, stateless)
              │
              ├─▶ vibes.ai  (create batch, start generation, poll SSE)
              └─▶ Cloudflare R2  (store generated MP4, public URL)
```

Render keeps nothing. R2 holds every generated video under `vibes/<batch_id>/<item_id>.mp4`. Public URLs are permanent.

---

## Quickstart (5 min)

### 1. Clone

```bash
git clone https://github.com/<you>/vibes-api.git
cd vibes-api
```

### 2. Create the Cloudflare R2 bucket (one-time)

1. Cloudflare dashboard → **R2 → Create bucket** → name: `remotion-assets`.
2. R2 → `remotion-assets` → **Settings → Public access** → connect a custom domain or use the auto-generated `*.r2.dev` URL.
3. R2 → `remotion-assets` → **Settings → CORS** → paste:

   ```json
   [{
     "AllowedOrigins": ["*"],
     "AllowedMethods": ["GET", "HEAD"],
     "AllowedHeaders": ["*"],
     "ExposeHeaders": ["Content-Range", "Content-Length"],
     "MaxAgeSeconds": 3600
   }]
   ```

4. R2 → **Manage R2 API Tokens** → create a token with **Object Read & Write** scoped to `remotion-assets`. Save the **Access Key ID** and **Secret Access Key**.

### 3. Deploy to Render

1. Push this repo to GitHub.
2. Render dashboard → **New + → Blueprint Instance** → pick the repo.
3. Render reads `render.yaml` and creates the web service.
4. After first deploy, open the service → **Environment** → set:
   - `R2_ENDPOINT` — e.g. `https://<account-id>.r2.cloudflarestorage.com`
   - `R2_ACCESS_KEY_ID`
   - `R2_SECRET_ACCESS_KEY`
5. Trigger **Manual Deploy** so the env vars take effect.

### 4. Get a vibes.ai session cookie

1. Open https://vibes.ai and log in.
2. DevTools → Application → Cookies → `meta_session` → copy the value (no `meta_session=` prefix).
3. Treat this as a password. Rotate it if it leaks.

### 5. First request

```bash
SERVICE=https://vibes-api-xxxx.onrender.com
COOKIE=eb2caef0-8321-4395-8aff-22cfae4be04d.DROq8SN788KAVqI38jL6c4mAaNWNgCHc-He8g7H0B38

curl $SERVICE/healthz

curl -H "X-Vibes-Session: $COOKIE" -H "Content-Type: application/json" \
     -d '{"prompt":"a dancing cat","resolution":"720p","count":1}' \
     $SERVICE/generate
```

Response:

```json
{
  "batch_id": "batch-...",
  "project_id": "...",
  "items": [
    {"item_id": "...", "video_url": "...", "image_url": "...",
     "r2_url": "https://pub-...r2.dev/vibes/<batch>/<item>.mp4",
     "filename": "vibes/<batch>/<item>.mp4", "size": 1234567}
  ]
}
```

Open `r2_url` in a browser to verify playback.

---

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/healthz` | Liveness + R2 status |
| `POST` | `/projects` | Create a vibes.ai project |
| `POST` | `/uploads` | Upload a file, returns its asset ID |
| `POST` | `/generate` | Text-to-video generation |
| `POST` | `/frames` | Frame-to-frame (start + end) generation |

Full schemas: `GET /docs` (Swagger) and `GET /redoc`.

### `GET /healthz`

```bash
curl https://<service>.onrender.com/healthz
# {"ok":true,"r2":true}
```

### `POST /projects`

```bash
curl -H "X-Vibes-Session: $COOKIE" -H "Content-Type: application/json" \
     -d '{"name":"My project"}' \
     https://<service>.onrender.com/projects
# {"project_id":"5eae62ae-..."}
```

### `POST /uploads`

```bash
curl -H "X-Vibes-Session: $COOKIE" \
     -F "file=@start.png" -F "project_id=$PROJECT_ID" \
     https://<service>.onrender.com/uploads
# {"media_id":"1123...","cdn_url":"https://...","asset_id":"-wGorR2L..."}
```

### `POST /generate`

```bash
curl -H "X-Vibes-Session: $COOKIE" -H "Content-Type: application/json" \
     -d '{"prompt":"a dancing cat","resolution":"720p","count":1}' \
     https://<service>.onrender.com/generate
```

Optional fields:

- `count`: 1-4 (default 1).
- `resolution`: `480p` or `720p` (default `720p`).
- `project_id`: reuse an existing project; otherwise one is created.
- `download`: omit for default R2 upload, or `stream` / `base64` for inline delivery.

#### Inline stream (no R2)

```bash
curl -H "X-Vibes-Session: $COOKIE" -H "Content-Type: application/json" \
     -d '{"prompt":"a dancing cat","count":1,"download":"stream"}' \
     https://<service>.onrender.com/generate -o out.mp4
```

#### Inline base64 (no R2)

```bash
curl -H "X-Vibes-Session: $COOKIE" -H "Content-Type: application/json" \
     -d '{"prompt":"a dancing cat","count":2,"download":"base64"}' \
     https://<service>.onrender.com/generate
```

### `POST /frames`

```bash
curl -H "X-Vibes-Session: $COOKIE" \
     -F "start=@scene_001.png" \
     -F "end=@scene_002.png" \
     -F "prompt=smooth animate" \
     -F "resolution=720p" \
     -F "count=1" \
     https://<service>.onrender.com/frames
```

Same delivery flags as `/generate` (`download=stream`, `download=base64`).

---

## Environment Variables

| Variable | Required | Example | Purpose |
|---|---|---|---|
| `R2_ENDPOINT` | for default mode | `https://<id>.r2.cloudflarestorage.com` | R2 S3-compatible endpoint |
| `R2_ACCESS_KEY_ID` | for default mode | `…` | R2 API token access key |
| `R2_SECRET_ACCESS_KEY` | for default mode | `…` | R2 API token secret |
| `R2_BUCKET` | no (default `remotion-assets`) | `remotion-assets` | Bucket name |
| `R2_PUBLIC_URL` | for default mode | `https://pub-...r2.dev` | Public URL prefix |
| `VIBES_API_TOKEN` | no | any string | Optional token gate (see Security) |

If any R2 var is missing, the service still boots but `/generate` and `/frames` default mode returns 503; use `download=stream` or `download=base64` instead.

---

## Security Notes

1. **Rotate any leaked credentials** before deploying. The vibes.ai cookie and R2 keys are bearer credentials; treat them as passwords.
2. **Add an API token gate** (recommended if the URL is reachable from the open internet):

   ```python
   # app/deps.py
   def require_token(x_api_token: str | None = Header(default=None)):
       expected = os.environ.get("VIBES_API_TOKEN", "")
       if expected and x_api_token != expected:
           raise HTTPException(status_code=401)
   ```

   Then add `Depends(require_token)` to every route.
3. **R2 public URLs are permanent.** Anyone with the link can fetch the file. If that is not acceptable, switch `app/storage.py` to presigned URLs (one-line change) and the bucket can stay private.
4. **The vibes.ai cookie expires.** When the service starts returning 401 from vibes.ai, log back into vibes.ai and update your `X-Vibes-Session` header.
5. **Do not commit the cookie** to this repo. Keep it in your shell or password manager.

---

## Limitations

- **Render Free sleeps after 15 min idle.** First request after sleep has a ~30s cold start.
- **512 MB RAM.** Multiple concurrent generations can OOM; this service does not serialize requests.
- **No persistent state.** Stateless by design — every call is end-to-end through vibes.ai.
- **No auth on the FastAPI layer by default.** See Security above.
- **No `/streams/{batch_id}` endpoint.** SSE over Render's proxy is unreliable; the service polls and returns final results instead.
- **No retries beyond vibes.ai's natural ones.**
- **No rate limiting.** Add it upstream (Cloudflare Access, nginx, etc.) if needed.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `/healthz` returns `{"r2":false}` | Missing R2 env vars | Set `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_PUBLIC_URL` on Render |
| `/generate` returns 503 | R2 not configured | Either set R2 env vars, or pass `download=stream`/`download=base64` |
| `/generate` returns 401 from vibes.ai | Cookie expired | Re-login on vibes.ai, copy new `meta_session` |
| `/generate` returns 502 with `NoCredentialsError` | boto3 env vars not set on Render | Set the four R2 vars and redeploy |
| Generated MP4 plays but has wrong audio | Some R2 default MIME | The service sets `Content-Type: video/mp4` explicitly; verify with `curl -I <r2_url>` |
| `fbcdn.net` URL 403s in logs | Signed URL expired | Service downloads the file immediately after generation, before expiry |
| Render shows service sleeping | Free plan idle timeout | First request after idle takes ~30s; upgrade to a paid plan to avoid |

---

## License

MIT.