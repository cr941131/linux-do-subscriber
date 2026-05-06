"""Check or repair AGENTS.md / CLAUDE.md / GEMINI.md as a synchronized triple.

Two modes are supported:

- ``hardlink`` (default): the three files share the same inode. Detection is
  cheap and ``edit one, see in all three`` is automatic.
- ``copy``: the three files are independent copies whose contents must match.
  Use this on filesystems that cannot create hardlinks (ReFS, exFAT, some
  WSL cross-drive setups, certain CI containers).

``check`` exits non-zero on any inconsistency or missing file. ``repair``
takes ``AGENTS.md`` as the source of truth and rebuilds the other two; if
``AGENTS.md`` is the missing one, pass ``--from=claude`` or ``--from=gemini``
to nominate a different source after manual review.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LINK_NAMES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")
LINK_PATHS = [ROOT / name for name in LINK_NAMES]


def path_for(name: str) -> Path:
    for p in LINK_PATHS:
        if p.name.lower() == name.lower():
            return p
    raise SystemExit(f"unknown link name: {name}")


def link_key(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_dev, stat.st_ino


def file_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def describe() -> list[str]:
    rows = []
    for path in LINK_PATHS:
        key = link_key(path)
        if key is None:
            rows.append(f"{path.name}: missing")
            continue
        stat = path.stat()
        rows.append(f"{path.name}: dev={key[0]} inode={key[1]} nlink={stat.st_nlink} size={stat.st_size}")
    return rows


def all_present() -> bool:
    return all(p.is_file() for p in LINK_PATHS)


def is_hardlink_group() -> bool:
    keys = [link_key(p) for p in LINK_PATHS]
    return all(k is not None for k in keys) and len(set(keys)) == 1


def is_content_equal() -> bool:
    if not all_present():
        return False
    texts = {file_text(p) for p in LINK_PATHS}
    return len(texts) == 1


def detect_mode() -> str:
    if is_hardlink_group():
        return "hardlink"
    if is_content_equal():
        return "copy"
    return "broken"


def command_check(args: argparse.Namespace) -> None:
    if args.verbose:
        print("\n".join(describe()))
    if not all_present():
        missing = [p.name for p in LINK_PATHS if not p.is_file()]
        raise SystemExit(f"missing file(s): {', '.join(missing)}")

    actual = detect_mode()
    if args.mode == "auto":
        if actual == "broken":
            raise SystemExit(
                "AGENTS.md / CLAUDE.md / GEMINI.md group is broken: "
                "neither all-hardlinked nor content-equal"
            )
    else:
        if actual != args.mode:
            raise SystemExit(
                f"expected mode={args.mode} but detected mode={actual}"
            )
    print(f"link group ok (mode={actual})")


def repair_target(source: Path, target: Path, mode: str, force: bool) -> None:
    if mode == "hardlink":
        try:
            if target.exists() and source.samefile(target):
                return
        except FileNotFoundError:
            pass
    elif mode == "copy":
        if target.exists() and file_text(target) == file_text(source):
            return

    if target.exists() and not force:
        if file_text(target) != file_text(source):
            raise SystemExit(
                f"{target.name} content differs from {source.name}; "
                f"rerun with --force only after review"
            )

    if target.exists():
        target.unlink()

    if mode == "hardlink":
        try:
            os.link(source, target)
        except OSError as exc:
            raise SystemExit(
                f"failed to hardlink {target.name} (errno={exc.errno}: {exc.strerror}). "
                f"If this filesystem does not support hardlinks, rerun with --mode=copy."
            ) from exc
    elif mode == "copy":
        shutil.copyfile(source, target)
    else:
        raise SystemExit(f"unknown mode: {mode}")

    print(f"synced {target.name} <- {source.name} (mode={mode})")


def resolve_source(from_arg: str | None) -> Path:
    if from_arg is None:
        source = path_for("AGENTS.md")
        if not source.is_file():
            raise SystemExit(
                "AGENTS.md is missing. Either restore it, or rerun with "
                "--from=claude or --from=gemini to nominate a different source."
            )
        return source
    source = path_for(f"{from_arg.upper()}.md")
    if not source.is_file():
        raise SystemExit(f"--from={from_arg} but {source.name} does not exist")
    return source


def command_repair(args: argparse.Namespace) -> None:
    source = resolve_source(args.from_)
    targets = [p for p in LINK_PATHS if p != source]

    mode = args.mode
    if mode == "auto":
        # Auto-pick: keep current mode if intact, else default to hardlink.
        current = detect_mode()
        mode = "copy" if current == "copy" else "hardlink"

    for target in targets:
        repair_target(source, target, mode, args.force)

    actual = detect_mode()
    if actual == "broken":
        print("\n".join(describe()), file=sys.stderr)
        raise SystemExit("repair failed")

    if source.name != "AGENTS.md":
        print(
            f"note: source was {source.name}; consider renaming it back to AGENTS.md "
            f"so that future repairs default to AGENTS.md as source.",
            file=sys.stderr,
        )

    print(f"link group ok (mode={actual})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="Verify the three files are consistent.")
    check.add_argument("--verbose", action="store_true")
    check.add_argument(
        "--mode",
        choices=("auto", "hardlink", "copy"),
        default="auto",
        help="Enforce a specific mode; default 'auto' accepts either.",
    )
    check.set_defaults(func=command_check)

    repair = sub.add_parser("repair", help="Rebuild CLAUDE.md and GEMINI.md from AGENTS.md.")
    repair.add_argument(
        "--mode",
        choices=("auto", "hardlink", "copy"),
        default="auto",
        help="hardlink (default for fresh repos) or copy (for filesystems without hardlink support).",
    )
    repair.add_argument(
        "--from",
        dest="from_",
        choices=("agents", "claude", "gemini"),
        default=None,
        help="Override which file is treated as the source of truth (use only when AGENTS.md is missing).",
    )
    repair.add_argument(
        "--force",
        action="store_true",
        help="Overwrite differing target content after manual review.",
    )
    repair.set_defaults(func=command_repair)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    # Force UTF-8 on stdout/stderr to keep output readable on Windows consoles
    # whose default code page is cp936/cp1252.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    main(sys.argv[1:])
