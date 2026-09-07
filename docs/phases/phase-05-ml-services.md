# Phase 05 — Embedding and ASR services

**Objective.** Two HTTP services — embeddings and transcription — each with a container
implementation (CPU) and a host implementation (Metal/MLX), behind one contract.

**Reranking is not built here.** OpenViking owns chunking, embedding orchestration, and
reranking (D-02). `athena-ml` serves embeddings *to OpenViking*, not to the agent.

**Preconditions.** Phase 04 gate green.

**Read first:** [`03-decisions.md`](../03-decisions.md#d-06--ml-services-are-http-endpoints-with-two-implementations)
for why this is not a library import.

---

## The constraint, restated

Docker Desktop, Podman, and colima run Linux containers on macOS inside a VM built on
`Hypervisor.framework`, which exposes no virtual GPU. **A container on the Mac mini cannot
reach Metal or the Neural Engine.** This is architectural. Whisper large-v3 on VM CPU is
roughly an order of magnitude slower than on Metal.

Hence: the contract is HTTP, and there are two implementations. In CI and on Linux,
containers. In production on the Mac mini, native host processes. Config picks the base
URL; nothing else in the system knows.

---

## Steps

### 1. The contract

`src/athena/ml/contract.py` — request and response models shared by both
implementations and by every client, plus the OpenAI-compatible route OpenViking calls.

```
POST /embed
{ "model": "...", "texts": ["..."], "input_type": "document" | "query" }
→ { "model": "...", "dimension": 1024, "embeddings": [[...]] }

POST /v1/embeddings     (OpenAI-compatible; this is the route OpenViking calls)
{ "model": "...", "input": ["..."] }
→ { "model": "...", "data": [ { "index": 0, "embedding": [...] } ] }

POST /transcribe        (ASR service only)
  multipart: file + options JSON
→ { "duration_s": ..., "segments": [ { start, end, speaker, text, words: [...] } ] }

GET /health
→ { "status": "ok", "device": "cpu" | "mps", "models_loaded": [...] }
```

`input_type` matters: several embedding model families expect an asymmetric prefix for
queries versus documents, and omitting it costs measurable recall. The service applies the
prefix; callers do not.

`/health` reporting `device` is how `just doctor` tells you the host service silently fell
back to CPU — a real failure mode after an OS update.

### 2. Container implementation

`src/athena/ml/server.py`, FastAPI, `sentence-transformers` on CPU. Models cached to
`/models`, downloaded at build time in the Dockerfile rather than at first request, so a
cold start is not a five-minute stall.

Batching, `torch.inference_mode()`, and a concurrency limit from config.

### 3. Host implementation

`host/ml/` — same API, MLX backend. Installed by `just install-host-services` into its own
virtualenv (**not** the project's — its dependency tree is heavy and macOS-specific and
must not be in `pyproject.toml`).

### 4. ASR service

`host/asr/` — WhisperX-shaped pipeline (D-11):

1. VAD (**not optional** — Whisper hallucinates confidently during silence, and a lecture
   hall has a lot of it)
2. Decode via the MLX Whisper backend
3. wav2vec2 forced alignment for word timestamps (the decoder's own timing drifts)
4. pyannote diarization
5. **Assembly**: assign each *aligned word* to the speaker whose turn contains its
   midpoint. Do not attempt to match segment boundaries between the diarizer and the
   decoder — they use different segmentations by construction and boundary matching
   degenerates into tolerance constants that never quite work.

Long audio is windowed with overlap inside the service and stitched with global
timestamps. Concurrency is 1 by default: two 90-minute lectures in parallel will page on
16 GB.

A container ASR implementation exists too (faster-whisper, int8, CPU), used only in CI —
it is slow, and the tests that use it use 30-second clips.

### 5. Clients

`src/athena/ml/client.py` — one client per endpoint, base URL from config, with retry,
timeout, and a circuit breaker. When the service is down, the client raises; per I-12 the
caller requeues rather than degrading silently.

### 6. `just install-host-services`

Creates the virtualenvs, downloads model weights, templates the `launchd` plists with the
real username (not a committed literal — I-06), loads them, and verifies `/health` on both
ports.

---

## Files produced

```
src/athena/ml/{__init__,contract,server,client,__main__}.py
host/ml/**
host/asr/**
host/launchd/{com.athena.asr.plist.tmpl,com.athena.ml.plist.tmpl}
docker/ml.Dockerfile
tests/integration/ml/**
```

## Tests required

1. Contract conformance, parametrized over both implementations: identical request →
   structurally identical response.
2. Embeddings are deterministic for identical input on a given implementation.
3. `input_type` changes the embedding (proving the prefix is applied).
4. The OpenAI-compatible route and the native route produce identical vectors for the same
   input.
5. Batch of size N returns N embeddings, in order.
6. `/health` reports the device truthfully.
7. ASR on a 30-second fixture clip: segments produced, word timestamps monotonic and
   within duration, speakers assigned.
8. ASR with `diarize=false` produces no speaker labels and does not crash.
9. Client circuit breaker opens after the configured failures and raises rather than
   hanging.
10. Client timeout raises rather than blocking a worker indefinitely.

## Exit gate

- Both implementations pass the contract tests, on both routes.
- On the Mac mini: `just install-host-services`, then `/health` reports `device: mps` on
  both host services.
- A 30-second clip transcribes end to end on the host in under 10 seconds.
- Measured and recorded in the phase's commit message: time to transcribe a 60-minute
  file on the host. This number sets the ingestion expectations everything downstream
  assumes.
