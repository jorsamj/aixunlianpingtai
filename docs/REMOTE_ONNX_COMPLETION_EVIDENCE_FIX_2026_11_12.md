# Remote ONNX completion evidence and legacy recovery (2026-11-12)

## Production finding (read only)

An uploaded ONNX weight mapped to the external NVIDIA generic environment remained UNSELECTED with EXTERNAL_WEIGHT_COMPLETION_UNCONFIRMED. Local ONNX task 0187ba8ae32e2400b46e5c81 has a timezone-qualified UTC manifest completion and verified SHA256. Earlier remote job 5c2d3801747e49fd946f6754 stored a naive local finished_at and omitted output sha256/size_bytes and manifest_path, although the downloaded archive has a manifest with an offset-aware created_at. No production data was touched.

## Scoped correction

- Legacy remote receiver records real downloaded SHA256 and byte length for every output and a separate timezone-aware UTC local receipt timestamp; this is **receipt**, not a fabricated remote worker timestamp.
- The original conversion source trace is sent to the existing remote endpoint.
- Model asset discovery considers an adjacent legacy remote manifest when an old job did not persist manifest_path. It accepts only the saved remote_job_id (or local job ID) and a manifest with exact local source SHA256, model output SHA256 and byte size. A verified conversion-generated manifest written after output creation can provide its timezone-aware completed_at or created_at. A naive timestamp is never interpreted as UTC and file mtime is never used.
- Unmatched manifests remain untrusted and block automatic ranking as before. Automatic delivery choice, Weight deduplication, remote identity and readback safeguards are unchanged.
- Historical recovery is read-only at discovery time. No historical job files, timestamps or production database rows are edited by this patch.

## Validation

Isolated regressions cover UTC and model hash/size on remote receipts and accept/reject legacy remote manifest identities. Full CI is required before deployment. After deploying with separate authorization, read the publication status for the affected version; check both ONNX candidates' source and output binding, selected artifact and external computePlatformId before an authorized single publish. Confirm remote weightId and readback.

No deployment, OSS mutation or external Weight write is part of this change.
