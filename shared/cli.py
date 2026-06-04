"""Common CLI flags shared by all demos."""

from . import config


def add_common_args(parser):
    parser.add_argument(
        "--mock", action="store_true",
        help="mock the board hardware and run on a laptop (Gemma stays REAL via gguf)",
    )
    parser.add_argument(
        "--backend", choices=["gguf", "template"], default=None,
        help="LM backend: gguf (default, real Gemma 3 270M) · template (no model)",
    )


def apply_common_args(args):
    if getattr(args, "mock", False):
        config.set_mock(True)
    if getattr(args, "backend", None):
        config.set_backend(args.backend)
    print(f"mode: hardware={'MOCK' if config.MOCK else 'BOARD'} · gemma={config.BACKEND}")
