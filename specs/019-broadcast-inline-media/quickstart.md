# Quickstart: validate inline media in WhatsApp broadcasts

Contract: [contracts/whatsapp-broadcasts-multipart.openapi.yaml](./contracts/whatsapp-broadcasts-multipart.openapi.yaml). Records and limits: [data-model.md](./data-model.md).

## Prerequisites

- Local: PostgreSQL and Redis as for the rest of the suite, and libmagic (`brew install libmagic` on macOS, `apt install libmagic1` on Debian/Ubuntu). Without libmagic, only the tests that detect types fail; Django still loads (research R2).
- Fixtures already in the repository: `media/test_media/steve.marten.jpg`, `snow.mp4`, `allo.wav`. `snow.m4a` is a copy of `snow.mp4` and still has video, so automated tests use `audio_only_mp4_bytes()` from `temba/tests/media.py` as the audio file. For a manual audio-only check, use a real `.m4a` recording.

## Automated checks

```bash
poetry run coverage run manage.py test \
  temba.msgs.usecases.tests.test_broadcast_media \
  temba.utils.s3 \
  temba.api.v2.tests \
  temba.api.v2.internals.broadcasts \
  temba.fastapi_app
./code_check.py
```

Expected: all green, including the unchanged JSON, idempotency, and FastAPI bridge tests (AC-1, AC-10).

## Manual checks against staging (private bucket, Courier with courier#243)

Use an API Key of a staging org with a WhatsApp channel and a test group.

1. **One image (AC-2)**

   ```bash
   curl -sS -X POST "$FLOWS/api/v2/whatsapp_broadcasts.json" \
     -H "Authorization: Token $API_KEY" \
     -F 'payload={"groups":["'$GROUP'"],"msg":{"text":"inline media check"}}' \
     -F 'files=@media/test_media/steve.marten.jpg'
   ```

   Expect `201`. `metadata.attachments[-1]` is `image/jpeg:<STORAGE_URL>/attachments/<org_id>/broadcasts/<sha256>.jpg`, with no `X-Amz-` in it. `shasum -a 256 media/test_media/steve.marten.jpg` matches `<sha256>`. The group's phone receives the image.

2. **Dedup (AC-4, SC-003)**: repeat step 1 with `-w '%{time_total}\n'`. Expect the same URL. The S3 access log or CloudTrail shows no second `PutObject` for that key. Time a JSON broadcast to the same group and the transfer of the file. The repeated multipart time is within 10% of those two added together. This is one sample, not a percentile run.

3. **Order (AC-3)**: send `payload.msg.attachments` with one public URL, plus `-F files=@snow.mp4 -F files=@steve.marten.jpg`. Expect `[<url>, video/mp4:..., image/jpeg:...]`.

4. **Rejections (AC-5)**: `-F files=@media/test_media/allo.wav` returns `400` with `{"files": {"0": [...]}}`. Eleven `files` parts return `400`. A malformed `payload` returns `400` on `payload`. No new object appears under `attachments/<org_id>/broadcasts/`.

5. **Internal endpoint (AC-7, AC-8)**: post step 1 to `/api/v2/internals/whatsapp_broadcasts` with an internal token, `"project"` in `payload`, and `-H 'Idempotency-Key: qs-1'`. Repeat it and expect the same body replayed. Repeat it with `snow.m4a` instead and expect `409`.

6. **Storage outage (AC-6)**: not run in staging. It is covered by the automated tests, which patch the storage and the dedup client to raise.

## Rollout gates (must be confirmed before production)

- Ingress (`proxy-body-size`) and Kong (`client_max_body_size` for the `broadcasts` alias) accept at least `MAX_BROADCAST_MULTIPART_BYTES` (about 103 MiB) on both routes. Request buffering stays on, so slow uploads do not hold a gunicorn sync worker.
- The image built from `docker/Dockerfile` includes `libmagic1`: `python -c "import magic; print(magic.from_file('/etc/hostname', mime=True))"` inside the container.
- The Flows IAM role has `s3:PutObject` on `attachments/*` in `AWS_STORAGE_BUCKET_NAME`. This is unchanged from the existing uploads; no `HeadObject` is used (research R4).
- No S3 lifecycle rule expires `attachments/*/broadcasts/` within `BROADCAST_MEDIA_DEDUP_TTL_SECONDS` (7 days).
