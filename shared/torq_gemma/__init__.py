"""Torq NPU backend for Gemma 3 (vendored from synaptics-astra-demos/sl2610-examples,
Apache-2.0). Runs a compiled .vmfb on the Coral/Torq NPU via torq.runtime.

NOTE: on this board the NPU LLM is NOT faster than llama.cpp on the CPU (see
docs/npu-llm-findings.md). This backend exists to showcase the board running an
LLM on its NPU; hello_world uses the faster CPU path.
"""
from .runner import GemmaTorq, load_gemma  # noqa: F401
