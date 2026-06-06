"""npu_chat - chat with Gemma 3 270M running on the Coral/Torq NPU.

This demo showcases the board running a *large language model on its NPU* (not the
CPU): a compiled bf16 `.vmfb` executed via `torq.runtime` on the Coral/Torq NPU.

Honesty note: on this board the NPU is NOT faster than llama.cpp on the CPU for
Gemma-270M generation (~4 tok/s NPU vs ~6.5 tok/s CPU) - autoregressive decode is
per-token-overhead-bound, and quantization doesn't change that. See
../docs/npu-llm-findings.md. `hello_world/` uses the faster CPU path; this demo
exists to demonstrate the NPU LLM path end-to-end and surface the real tok/s.

Board only (needs torq.runtime + the compiled model). There is no --mock path.

  ./run_npu_chat.sh                      # on the board

Model dir (CORAL_NPU_MODEL, a .vmfb whose folder also holds token_embeddings.npy,
token_id_lut.npy, config.json, tokenizer.json) is built with the Torq compiler -
see ../docs/npu-llm-findings.md for the exact pipeline.
"""

import argparse
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared import config, webserver

_DEFAULT_MODEL = os.path.join(os.path.dirname(__file__), "..", "models", "npu_gemma", "model.vmfb")
MODEL = os.environ.get("CORAL_NPU_MODEL", _DEFAULT_MODEL)

_model = None
_lock = threading.Lock()          # torq.runtime, like llama.cpp, is not reentrant


def _load():
    global _model
    if _model is None:
        from shared.torq_gemma import load_gemma
        t0 = time.time()
        _model = load_gemma(use_llama=False, model_path=MODEL, n_threads=2)
        print(f"[npu] Gemma loaded on the NPU in {time.time()-t0:.1f}s")
    return _model


def chat(msg: str) -> dict:
    msg = (msg or "").strip()[:400]
    if not msg:
        return {"reply": ""}
    with _lock:
        m = _load()
        out = ""
        for partial in m.stream_response(msg):
            out = partial
        ms = m.last_infer_time_ms
        tps = m.last_n_output_tokens / (ms / 1000 + 1e-9)
    return {"reply": out.strip(),
            "tok_s": round(tps, 1),
            "ttft_ms": round(m.time_to_first_token_ms),
            "tokens": m.last_n_output_tokens,
            "device": "Coral/Torq NPU"}


def _on_action(params):
    if params.get("do") == "chat":
        return chat(params.get("msg", ""))


def main():
    parser = argparse.ArgumentParser(description="Chat with Gemma 3 270M on the Coral NPU")
    parser.parse_args()
    if not os.path.exists(MODEL):
        sys.exit(f"NPU model not found at '{MODEL}'. Set CORAL_NPU_MODEL or build it "
                 f"(see docs/npu-llm-findings.md).")

    webserver.serve(web_dir=os.path.join(os.path.dirname(__file__), "web"))
    webserver.set_action_handler(_on_action)
    print("npu_chat - Gemma 3 270M on the Coral/Torq NPU")
    print(f"loading model from {MODEL} (takes ~15s) ...")
    _load()                                   # warm up now, never auto-generate
    webserver.broadcast({"type": "ready", "device": "Coral/Torq NPU",
                         "mode": "MOCK" if config.MOCK else "BOARD"})
    print(f"ready - web up at http://<board-ip>:{config.WEB_PORT}  ·  Ctrl-C to quit")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
