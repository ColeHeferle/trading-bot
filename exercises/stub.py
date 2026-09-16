#!/usr/bin/env python3
"""Stub a module's function bodies so it can be rewritten from its tests.

Signatures, docstrings, imports, class definitions and every other statement
survive; each function body becomes a single ``raise NotImplementedError``.
The commit the module was stubbed from is recorded in a header comment, so
``--restore`` and the diff step keep working however many commits land on top.

    python exercises/stub.py --list
    python exercises/stub.py portfolio
    python exercises/stub.py --restore portfolio
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "trading_bot"

# name -> (exercise number, test files, one-line note)
MODULES = {
    "indicators": ("01", ["tests/test_indicators.py"], "rolling sma, ema, rsi"),
    "portfolio": ("02", ["tests/test_portfolio.py"], "cash, positions, fees, realized PnL"),
    "sizing": ("03", ["tests/test_sizing.py"], "position sizers"),
    "backtest": (
        "04",
        ["tests/test_backtest.py", "tests/test_multi_backtest.py", "tests/test_metrics.py"],
        "the replay loop and its metrics",
    ),
    "broker": ("05", ["tests/test_broker.py"], "Alpaca sandbox, retries, reconciliation"),
}

MARKER = "# STUBBED-FROM: "


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout


class Stubber(ast.NodeTransformer):
    """Empties every function body, keeping its docstring."""

    def __init__(self, brief: str) -> None:
        self.brief = brief
        self.count = 0

    def _stub(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
        self.generic_visit(node)
        body: list[ast.stmt] = []
        if ast.get_docstring(node, clean=False) is not None:
            body.append(node.body[0])
        body.append(
            ast.Raise(
                exc=ast.Call(
                    func=ast.Name(id="NotImplementedError", ctx=ast.Load()),
                    args=[ast.Constant(value=f"{node.name}: see {self.brief}")],
                    keywords=[],
                ),
                cause=None,
            )
        )
        node.body = body
        self.count += 1
        return node

    visit_FunctionDef = _stub
    visit_AsyncFunctionDef = _stub


def module_path(name: str) -> Path:
    path = SRC / f"{name}.py"
    if not path.exists():
        raise SystemExit(f"no such module: {path.relative_to(ROOT)}")
    return path


def stubbed_from(path: Path) -> str | None:
    for line in path.read_text().splitlines()[:5]:
        if line.startswith(MARKER):
            return line[len(MARKER) :].strip()
    return None


def do_stub(name: str) -> None:
    number, tests, _ = MODULES[name]
    path = module_path(name)
    rel = path.relative_to(ROOT).as_posix()

    if stubbed_from(path):
        raise SystemExit(f"{rel} is already stubbed. Restore it first, or just start writing.")

    # The recorded commit has to match what is on disk, or the diff step lies.
    if git("status", "--porcelain", "--", rel).strip():
        raise SystemExit(
            f"{rel} has uncommitted changes. Commit or stash them first so the\n"
            "recorded commit matches what is being replaced."
        )

    sha = git("rev-parse", "HEAD").strip()
    brief = f"exercises/{number}-{name}.md"

    tree = ast.parse(path.read_text())
    stubber = Stubber(brief)
    stubber.visit(tree)
    ast.fix_missing_locations(tree)

    header = (
        f"{MARKER}{sha}\n"
        f"# EXERCISE {number}: rewrite this module from {' and '.join(tests)}.\n"
        f"# Brief: {brief}   Restore: python exercises/stub.py --restore {name}\n"
    )
    path.write_text(header + ast.unparse(tree) + "\n")

    print(f"Stubbed {rel} — {stubber.count} function bodies removed.")
    print(f"Recorded commit {sha[:10]} for the diff step.\n")
    print("Baseline, then get it green:")
    print(f"  pytest {' '.join(tests)}")
    print("  pytest")
    print(f"\nRead {brief} before you start. Do not read the original first.")


def do_restore(name: str) -> None:
    path = module_path(name)
    rel = path.relative_to(ROOT).as_posix()
    sha = stubbed_from(path)
    if not sha:
        raise SystemExit(f"{rel} is not stubbed — nothing to restore.")
    path.write_text(git("show", f"{sha}:{rel}"))
    print(f"Restored {rel} from {sha[:10]}.")
    print("Your rewrite is gone unless you committed it. `git reflog` if that was a mistake.")


def do_list() -> None:
    print(f"{'module':<12} {'ex':<4} {'state':<10} tests")
    for name, (number, tests, note) in MODULES.items():
        path = SRC / f"{name}.py"
        state = "stubbed" if path.exists() and stubbed_from(path) else "intact"
        lines = sum(len((ROOT / t).read_text().splitlines()) for t in tests if (ROOT / t).exists())
        print(f"{name:<12} {number:<4} {state:<10} {' '.join(tests)} ({lines} lines)")
        print(f"{'':<12} {'':<4} {'':<10} {note}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("module", nargs="?", choices=sorted(MODULES), help="module to stub")
    parser.add_argument("--restore", metavar="MODULE", choices=sorted(MODULES))
    parser.add_argument("--list", action="store_true", help="show every exercise and its state")
    args = parser.parse_args()

    if args.list:
        do_list()
    elif args.restore:
        do_restore(args.restore)
    elif args.module:
        do_stub(args.module)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
