"""Regression test for the CLI surface itself.

main.py once silently shipped with only 2 of its 6 subcommands (draft,
enrich) - career-pages, fanuc, team-page, and sync-jsonl existed only in
scattered prompt text, never in committed code, and every unit test on the
underlying scraper functions stayed green throughout because none of them
exercise the CLI wiring. This test checks the CLI surface directly so that
regression can't hide behind passing unit tests again.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main as main_module  # noqa: E402

EXPECTED_SUBCOMMANDS = {"targets", "career-pages", "fanuc", "team-page", "sync-jsonl", "draft", "enrich"}


def test_help_lists_all_subcommands(capsys):
    try:
        main_module.main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    captured = capsys.readouterr()
    for name in EXPECTED_SUBCOMMANDS:
        assert name in captured.out, f"'{name}' subcommand missing from --help output"


def test_each_subcommand_help_does_not_error(capsys):
    for name in EXPECTED_SUBCOMMANDS:
        try:
            main_module.main([name, "--help"])
        except SystemExit as exc:
            assert exc.code == 0, f"`{name} --help` exited with {exc.code}"
