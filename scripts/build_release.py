#!/usr/bin/env python3
"""Build a shareable EvalDesk wheel, skill, and installation bundle."""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def project_version() -> str:
    text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', text, re.MULTILINE)
    if match is None:
        raise ValueError("Could not read the project version from pyproject.toml")
    return match.group(1)


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(release_root: Path) -> None:
    files = sorted(
        path
        for path in release_root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    )
    lines = [
        f"{file_hash(path)}  {path.relative_to(release_root).as_posix()}"
        for path in files
    ]
    (release_root / "SHA256SUMS").write_text(
        "\n".join(lines) + "\n", encoding="ascii"
    )


def build_release(output: Path, force: bool = False) -> Path:
    version = project_version()
    release_name = f"evaldesk-{version}-local"
    output = output.expanduser().resolve()
    archive = output / f"{release_name}.zip"
    if archive.exists() and not force:
        raise FileExistsError(f"{archive} already exists; use --force to replace it")
    output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="evaldesk-release-") as temporary:
        temporary_root = Path(temporary)
        build_environment = temporary_root / "build-venv"
        subprocess.run(
            [sys.executable, "-m", "venv", str(build_environment)], check=True
        )
        builder = (
            build_environment / "Scripts" / "python.exe"
            if sys.platform == "win32"
            else build_environment / "bin" / "python"
        )
        wheels = temporary_root / "wheels"
        wheels.mkdir()
        subprocess.run(
            [
                str(builder),
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--wheel-dir",
                str(wheels),
                str(PROJECT_ROOT),
            ],
            check=True,
        )
        wheel_files = list(wheels.glob("evaldesk-*.whl"))
        if len(wheel_files) != 1:
            raise RuntimeError(f"Expected one EvalDesk wheel, found {wheel_files}")

        release_root = temporary_root / release_name
        release_root.mkdir()
        shutil.copy2(PROJECT_ROOT / "INSTALL.md", release_root / "INSTALL.md")
        shutil.copy2(PROJECT_ROOT / "README.md", release_root / "README.md")
        shutil.copy2(wheel_files[0], release_root / wheel_files[0].name)
        shutil.copytree(PROJECT_ROOT / "skill", release_root / "skill")
        (release_root / "scripts").mkdir()
        shutil.copy2(
            PROJECT_ROOT / "scripts" / "install_skill.py",
            release_root / "scripts" / "install_skill.py",
        )
        write_manifest(release_root)

        temporary_archive = Path(
            shutil.make_archive(
                str(temporary_root / release_name),
                "zip",
                root_dir=temporary_root,
                base_dir=release_name,
            )
        )
        if archive.exists():
            archive.unlink()
        shutil.move(str(temporary_archive), archive)
    return archive


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "dist"),
        help="directory for the release archive",
    )
    result.add_argument("--force", action="store_true", help="replace the archive")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        archive = build_release(Path(args.output), force=args.force)
    except (OSError, RuntimeError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"error: {exc}")
        return 1
    print(f"Built EvalDesk release: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
