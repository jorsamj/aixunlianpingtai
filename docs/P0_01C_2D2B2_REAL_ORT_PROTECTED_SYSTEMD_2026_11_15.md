# P0-01C 2D-2B2: actual ONNX Runtime CPU inside protected systemd

2026-11-15. feature/external-algorithm-publishing. **Production NO-GO**.

A new isolated CI-only root-owned ONNX systemd profile executes real ORT CPUExecutionProvider inference. Uses fixed root-owned venv (onnxruntime 1.22.1, numpy 2.2.6), sealed ONNX input, DynamicUser, PrivateDevices/DevicePolicy, journald InvocationID, and SHA256 of input/output. Tests cover actual inference, process reattachment, natural terminal and cancellation as UNKNOWN without StopReceipt.

Not wired to Node Agent, existing SupervisorService grant, central tasks.attempt / lease, original MODEL_CONVERSION Runner, output prepare/upload/confirm/finish or GPU. Ubuntu 22.04 systemd 249 is still incompatible with ExitType=cgroup; CI Ubuntu 24.04 cannot certify production. Frozen dependency versions and root-only permissions are not complete package supply-chain attestation. Existing legacy execution and front end unchanged. A800/4070 not touched.

Next: verify exact SHA CI, fix regressions, then separately integrate central lease, durable identity and complete result lifecycle without making a new scheduler or enabling supervisor-required.

## First CI RED and minimum security fix
Initial SHA fdac051e was rejected before model launch by ORT_RUNTIME_MUTABLE_HOLD: GitHub-hosted /opt did not satisfy trusted-root directory checks. Keep fail-closed; move CI-only fixed venv to root-controlled /run, preserving owner/mode and package checks. Revalidate exact new SHA; do not infer model execution success from prior test results.

## Second CI RED and targeted fix
SHA 9fa9ef65 passed root directory checks, but the venv/bin/python3 symlink was rejected because lstat reports symlink mode 0777 (not a writable-mode permission). Reject arbitrary links, keep root owner verification and the exact resolved /usr/bin/python3.12 allowlist, and ignore only symlink mode bits. New SHA must be independently tested before acceptance.
