# npu_chat

Chat with **Gemma 3 270M running on the Coral/Torq NPU** of the Coralboard — a
compiled bf16 `.vmfb` executed via `torq.runtime`, no CPU inference and no cloud.

This is the companion to `hello_world/` (which runs Gemma on the **CPU**). It
exists to show the board can run an LLM on its NPU, and it surfaces the **real**
tokens/sec next to every reply.

## Honest performance note

On this board the NPU is **not faster** than llama.cpp on the CPU for Gemma‑270M:

| | decode | prefill |
|---|---:|---:|
| CPU (llama.cpp Q8) | ~6.5 tok/s | ~38 tok/s |
| NPU (this demo) | ~4 tok/s | ~4.6 tok/s |

Autoregressive decode is per‑token‑overhead‑bound, and quantization (we tested
bf16) gives no speedup. Full analysis + the exact compile pipeline:
[`../docs/npu-llm-findings.md`](../docs/npu-llm-findings.md). For the fast chat,
use `hello_world/`.

## Run (board only)

Needs (a) a Python with `torq.runtime` + `numpy`/`ml_dtypes`/`tokenizers`, and
(b) the compiled model dir (`model.vmfb` + `token_embeddings.npy` (bf16) +
`token_id_lut.npy` + `config.json` + `tokenizer.json`).

```bash
./setup_npu_chat.sh        # builds .venv-npu from npu_chat/wheelhouse/
./run_npu_chat.sh          # open http://<board-ip>:8090
```

Or point at an existing setup:

```bash
CORAL_NPU_PY=/path/to/torq-venv/bin/python \
CORAL_NPU_MODEL=/path/to/model/model.vmfb \
./run_npu_chat.sh
```

There is **no laptop/--mock path** — `torq.runtime` and the NPU only exist on the
board.

## How the model is built

The `.vmfb` is produced with the Synaptics **Torq compiler** (x86‑only, run via an
amd64 Docker, emulated on Apple Silicon): export Gemma 3 270M → quantize to bf16 →
compile for the `torq` backend. Step‑by‑step (with all the version workarounds) in
[`../docs/npu-llm-findings.md`](../docs/npu-llm-findings.md). The runtime backend
(`shared/torq_gemma/`) is vendored from `synaptics-astra-demos/sl2610-examples`
(Apache‑2.0).

## Layout
```
npu_chat/main.py        web chat server (reuses shared/webserver.py)
npu_chat/web/           chat UI (shows device + tok/s per reply)
shared/torq_gemma/      Torq NPU Gemma backend (vendored, Apache-2.0)
models/npu_gemma/       compiled model (not in git; built via Torq)
```
