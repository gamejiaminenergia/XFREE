"""The terminal surface is frozen: it is the primary way to drive the pilot.

Adding frontends (a terminal UI, an HTTP service) must not take anything away
from the CLI.  This pins the pilots it accepts and every documented flag, the
way ``test_jev_prompt_contract`` pins the wire format.
"""

from __future__ import annotations

from jev_duum import cli

PILOTS = ("manual", "scripted", "random", "heuristic", "hunter", "jev", "jev-assisted")

FLAGS = (
    "--wad", "--map", "--duum-path", "--pilot", "--model", "--endpoint",
    "--prompt-version", "--decision-rate", "--max-stale-ticks", "--seed",
    "--headless", "--ticks", "--checkpoint-every", "--record",
    "--record-snapshots", "--no-world-model", "--mission", "--damage-log",
    "--replay", "--windowed", "--tui", "--log-calls", "--size", "--scale",
)


def test_every_pilot_is_still_accepted():
    assert cli.PILOTS == PILOTS
    parser = cli.make_parser()
    for pilot in PILOTS:
        assert parser.parse_args(["--pilot", pilot]).pilot == pilot


def test_every_documented_flag_is_still_there():
    help_text = cli.make_parser().format_help()
    missing = [flag for flag in FLAGS if flag not in help_text]
    assert not missing, f"flags that disappeared from the CLI: {missing}"


def test_the_console_entry_points_are_unchanged():
    import importlib

    for module in ("jev_duum.cli", "jev_duum.autopsy", "jev_duum.evaluation",
                   "jev_duum.prompt_eval"):
        assert callable(getattr(importlib.import_module(module), "main"))
