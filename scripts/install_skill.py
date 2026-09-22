#!/usr/bin/env python3
"""Install the bundled EvalDesk skill into an explicit Agent skills root."""
from __future__ import annotations

import argparse
import re
import shutil
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = PROJECT_ROOT / "skill" / "evaldesk"
NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def read_skill_name(skill_file: Path) -> str:
    text = skill_file.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md is missing YAML frontmatter")
    try:
        frontmatter = text.split("---\n", 2)[1]
    except IndexError as exc:
        raise ValueError("SKILL.md has incomplete YAML frontmatter") from exc
    values = {}
    for line in frontmatter.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    name = values.get("name", "")
    if not 2 <= len(name) <= 64 or not NAME_PATTERN.fullmatch(name):
        raise ValueError(f"SKILL.md has an invalid name: {name!r}")
    if not values.get("description"):
        raise ValueError("SKILL.md is missing a description")
    if not text.split("---\n", 2)[2].strip():
        raise ValueError("SKILL.md has an empty body")
    return name


def validate_skill(source: Path) -> str:
    skill_file = source / "SKILL.md"
    if not skill_file.is_file():
        raise ValueError(f"Missing skill file: {skill_file}")
    name = read_skill_name(skill_file)
    if source.name != name:
        raise ValueError(
            f"Skill directory {source.name!r} does not match name {name!r}"
        )
    for link in LINK_PATTERN.findall(skill_file.read_text(encoding="utf-8")):
        if "://" in link or link.startswith("#"):
            continue
        target = (source / link.split("#", 1)[0]).resolve()
        if not target.is_file():
            raise ValueError(f"SKILL.md references a missing file: {link}")
    return name


def install_skill(source: Path, target_root: Path, force: bool = False) -> Path:
    source = source.expanduser().resolve()
    target_root = target_root.expanduser().resolve()
    name = validate_skill(source)
    target_root.mkdir(parents=True, exist_ok=True)
    destination = target_root / name
    if destination.exists() and not force:
        raise FileExistsError(
            f"{destination} already exists; rerun with --force to replace it"
        )

    with tempfile.TemporaryDirectory(
        prefix=f".{name}-install-", dir=target_root
    ) as temporary:
        temporary_root = Path(temporary)
        staged = temporary_root / name
        shutil.copytree(source, staged)
        validate_skill(staged)

        backup = temporary_root / "previous"
        if destination.exists():
            destination.replace(backup)
        try:
            staged.replace(destination)
        except Exception:
            if backup.exists() and not destination.exists():
                backup.replace(destination)
            raise
    return destination


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Install the EvalDesk Agent skill into a local skills root"
    )
    result.add_argument(
        "--target-root",
        required=True,
        help="Agent skills root that will contain the evaldesk directory",
    )
    result.add_argument(
        "--source",
        default=str(DEFAULT_SOURCE),
        help="source skill directory; defaults to this release",
    )
    result.add_argument(
        "--force",
        action="store_true",
        help="replace an existing evaldesk skill installation",
    )
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        destination = install_skill(
            Path(args.source), Path(args.target_root), force=args.force
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}")
        return 1
    print(f"Installed EvalDesk skill: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
