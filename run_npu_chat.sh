#!/usr/bin/env bash
# Run the npu_chat demo on the board: Gemma 3 270M on the Coral/Torq NPU.
#
# Needs a Python with torq.runtime (+ numpy, ml_dtypes, tokenizers) and the
# compiled model dir. Both are produced by the Torq pipeline in
# docs/npu-llm-findings.md. Override the defaults via env:
#   CORAL_NPU_PY     python interpreter with torq.runtime installed
#   CORAL_NPU_MODEL  path to model.vmfb (its folder holds the peripheral files)
set -e
cd "$(dirname "$0")"

PY="${CORAL_NPU_PY:-$PWD/.venv-npu/bin/python}"
MODEL="${CORAL_NPU_MODEL:-$PWD/models/npu_gemma/model.vmfb}"

[ -x "$PY" ] || { echo "No torq python at '$PY'. Run ./setup_npu_chat.sh or set CORAL_NPU_PY."; exit 1; }
[ -f "$MODEL" ] || { echo "No NPU model at '$MODEL'. Build it (docs/npu-llm-findings.md) or set CORAL_NPU_MODEL."; exit 1; }

export CORAL_MOCK=0 CORAL_NPU_MODEL="$MODEL"
exec "$PY" -m npu_chat.main "$@"
