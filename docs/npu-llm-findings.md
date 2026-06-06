# Running an LLM on the Coralboard NPU — findings

Investigation (2026-06-06): can we run Gemma 3 on the **Coral/Torq NPU** of the
Coralboard (Astra SL2619) and make it **faster than the CPU**? Short answer:
**it runs on the NPU, but it is not faster than the CPU for this model** — and we
proved why with measurements, including building a quantized model ourselves.

## TL;DR

| Path | Decode | Prefill (long prompt) | RAM |
|------|-------:|----------------------:|----:|
| **CPU** — llama.cpp Gemma‑270M Q8 | **6.5 tok/s** | **~38 tok/s** | ~400 MB |
| NPU — Gemma‑270M fp32 (Synaptics' published vmfb) | 4.4 tok/s | ~4.6 tok/s | ~920 MB |
| NPU — Gemma‑270M **bf16** (we compiled this) | 4.07 tok/s | ~4.6 tok/s | ~1000 MB |

The NPU is slower at **both** decode and prefill. **Use the NPU for vision
(`synap_cli_*` CNNs, ~33 ms) and Gemma on the CPU.**

## Why the NPU isn't faster here

1. **Decode is memory/overhead‑bound, not compute‑bound.** Generating one token is
   a batch‑1, seq‑1 forward — tiny vector×matrix ops. The NPU's MAC array (its
   advantage) is idle; you're paying a fixed per‑token dispatch/execution cost
   (~225–245 ms across the 18 layers).
2. **Quantization does NOT help.** We compiled a **bf16** model (half the weight
   bytes of fp32) and it gave **0 % speedup** (4.07 vs 4.4 tok/s). That rules out
   weight memory bandwidth as the bottleneck, so int8 (4×) wouldn't help either.
3. **Prefill is also token‑by‑token here.** The published static model + the
   `GemmaTorq` runner prefill the prompt one token at a time (seq=1, no batching),
   so a 126‑token prompt takes **27.6 s** on the NPU vs **3 s** on the CPU
   (llama.cpp batches the prompt in parallel). The NPU's theoretical prefill win
   needs a seq>1 batched graph that the published export doesn't provide.

Synaptics' marketing "3.5× faster" is most likely a different metric (energy, or
prefill on a batched graph) or an unpublished optimized build (int8 lm_head +
split‑lm‑head, see their `GemmaDev` repo). The published
`Synaptics/gemma-3-270m-it-torq` model is **fp32**.

## How to compile a quantized Gemma for the NPU (it works — just isn't faster)

The Torq compiler is **x86_64‑only**, so it runs in an **amd64 Docker** image
(`ghcr.io/synaptics-torq/torq-compiler/compiler:main`), emulated on Apple Silicon.
Give Docker **~32 GB RAM** or the graph edit OOMs.

Gotchas (torq-tools `main` is ahead of every published compiler):

- `torq-tools` imports `torq.compile` (`add_iree_args`/`export_iree`/`process_iree_args`)
  but published wheels only ship `torq.compiler` (`compile_file`). Add a shim
  `src/torq/compile.py` and export ONNX‑only (`--skip-iree`); compile separately.
- Patch `model_export/hf.py` opset **22 → 20** (installed torch maxes at 20).
- torq-tools' internal optimum call omits `--task`; run it yourself:
  `optimum-cli export onnx <dir> --model unsloth/gemma-3-270m-it --task text-generation-with-past --opset 20`.
  Use the **ungated** mirror `unsloth/gemma-3-270m-it` (Google's is gated; Synaptics'
  prebuilt `model.onnx` has an incompatible KV‑concat axis).
- Make `convert_dtype/onnx.py` shape inference tolerant — bf16 `Sin` (rotary
  embeddings) breaks onnx 1.19 `infer_shapes`.

Pipeline:

```bash
torq-export-model gemma3 -s 270m --instruct-model --hf-repo unsloth/gemma-3-270m-it \
    --extract-embeddings --trim-vocab --skip-iree            # -> static fp32 ONNX
torq-quantize-model quantize -i static/model.onnx -o model_bf16.onnx \
    --bits 8 --dequantize-weights                            # int8 DQL does NOT compile
                                                             # (torq can't legalize block_size=32
                                                             #  DequantizeLinear); use bf16
python -m iree.compiler.tools.import_onnx model_bf16.onnx -o model_bf16.mlir
python -c "import torq.compiler as c; c.compile_file('model_bf16.mlir', output_file='model.vmfb')"
```

On the board, install the **matching** `torq_runtime` aarch64 wheel (compiler and
runtime must be the same build), convert `token_embeddings.npy` to **bf16** (the
model's embedding input is bf16), and run via the `GemmaTorq` runner from
`synaptics-astra-demos/sl2610-examples` (`utils/gemma`, `utils/inference`).

This is exactly what the `npu_chat/` demo packages — kept as a showcase that the
board *can* run an LLM on its NPU, even though the CPU path (`hello_world/`) is
faster for generation.
