#!/usr/bin/env bash
# Set up the npu_chat demo on the board: a venv with the Torq NPU runtime.
#
# Expects the Torq runtime + dep wheels in ./npu_chat/wheelhouse/ (aarch64, cp312)
# - these come from synaptics-astra-demos/sl2610-examples (wheelhouse/) plus a
# matching torq_runtime build (see docs/npu-llm-findings.md). The compiled model
# must already be at ./models/npu_gemma/ (build it with the Torq pipeline).
set -e
cd "$(dirname "$0")"
WH=npu_chat/wheelhouse

[ -d "$WH" ] || { echo "Missing $WH (Torq runtime + dep wheels). See docs/npu-llm-findings.md."; exit 1; }

python3 -m venv .venv-npu --system-site-packages
./.venv-npu/bin/pip install --no-index --find-links="$WH" \
  torq_runtime numpy ml_dtypes tokenizers 2>&1 | tail -3
./.venv-npu/bin/python -c "import torq.runtime, iree.runtime; print('torq runtime OK')"
echo "Done. Run with ./run_npu_chat.sh"
