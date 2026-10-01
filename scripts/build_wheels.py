"""Build the two importable distributions from this source tree.

Run from the repository root:

    .venv\\Scripts\\python.exe -X utf8 scripts\\build_wheels.py

Writes to ``dist/``:

    autoscriptor-<version>-py3-none-any.whl    framework layer
    zmxyol-<version>-py3-none-any.whl          game layer, depends on the above

Installing both lets a script author write against ``AutoScriptor`` and
``ZmxyOL`` without a source checkout.

Why a script and not ``python -m build``: this environment has no ``pip``,
``wheel`` or ``build`` module, and a wheel is a zip holding the package tree
plus three small metadata files. Writing it directly keeps the build offline,
byte-for-byte reproducible and easy to inspect.

What each distribution carries:

- ``autoscriptor`` is the framework layer, so it ships ``AutoScriptor/`` and
  nothing else. It must not import the game layer.
- ``zmxyol`` is the game layer together with the task-authoring surface,
  because the two are mutually dependent: ``ZmxyOL`` re-exports
  ``tasks.register_task`` while ``tasks.task_register`` runs
  ``from ZmxyOL import *``. ``ZmxyOL/assets/`` (UI map csv and reference
  images) ships as package data, and ``data/character/hero.py`` is copied in as
  ``ZmxyOL/character/_default_impl/hero.py`` so an install with no editable
  data tree still has a battle implementation.

The application layers (``orchestrator/``, ``backend/``, ``frontend/``) are not
packaged; they run from the source tree.
"""
from __future__ import annotations

import base64
import hashlib
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"

# Fixed timestamp so two builds of the same tree produce identical bytes.
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
GENERATOR = "autoscriptor-build-wheels"
LICENSE_FILE = "LICENSE"

EXCLUDED_DIRECTORY_NAMES = frozenset({"__pycache__"})
EXCLUDED_SUFFIXES = frozenset({".pyc", ".pyo"})


@dataclass
class WheelSpec:
    """One distribution: which packages it carries and what it declares."""

    distribution: str
    summary: str
    packages: tuple[str, ...]
    requires_dist: tuple[str, ...] = ()
    # Archive path -> content, for files that are staged rather than copied.
    staged_files: dict[str, bytes] = field(default_factory=dict)


def read_project_version() -> str:
    """The version declared once in ``pyproject.toml``."""
    project_table = _project_table()
    match = re.search(r'^version\s*=\s*"([^"]+)"', project_table, re.MULTILINE)
    if match is None:
        raise SystemExit("pyproject.toml 的 [project] 段里找不到 version")
    return match.group(1)


def read_project_dependencies() -> tuple[str, ...]:
    """The runtime requirements declared in ``pyproject.toml``.

    Parsed by hand rather than with ``tomllib`` because the interpreter running
    the build is 3.10 and the file is ours, flat and comment-only.
    """
    project_table = _project_table()
    start = project_table.index("dependencies = [")
    end = project_table.index("\n]", start)
    block = project_table[start:end]
    requirements: list[str] = []
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        requirements.extend(re.findall(r'"([^"]+)"', stripped))
    if not requirements:
        raise SystemExit("pyproject.toml 的 dependencies 解析结果为空")
    return tuple(requirements)


def build_specs(version: str) -> tuple[WheelSpec, WheelSpec]:
    """The two distributions, in install order."""
    framework = WheelSpec(
        distribution="autoscriptor",
        summary="AutoScriptor framework: device control, recognition and the script API",
        packages=("AutoScriptor",),
        requires_dist=read_project_dependencies(),
    )
    game_layer = WheelSpec(
        distribution="zmxyol",
        summary="ZmxyOL game layer: battle, navigation, task authoring and account domain",
        packages=("ZmxyOL", "tasks"),
        requires_dist=(f"autoscriptor=={version}",),
        staged_files={
            "ZmxyOL/character/_default_impl/hero.py": read_hero_implementation_bytes(),
        },
    )
    return framework, game_layer


def read_hero_implementation_bytes() -> bytes:
    """``data/character/hero.py``, staged as the shipped default implementation."""
    source = ROOT / "data" / "character" / "hero.py"
    if not source.is_file():
        raise SystemExit(f"找不到英雄实现，无法打包 zmxyol: {source}")
    return source.read_bytes()


def collect_archive_entries(spec: WheelSpec, version: str) -> dict[str, bytes]:
    """Every file the wheel contains, keyed by archive path."""
    entries: dict[str, bytes] = {}
    for package in spec.packages:
        entries.update(_collect_package_files(package))
    entries.update(spec.staged_files)

    dist_info = f"{spec.distribution}-{version}.dist-info"
    entries[f"{dist_info}/METADATA"] = render_metadata(spec, version).encode("utf-8")
    entries[f"{dist_info}/WHEEL"] = render_wheel_metadata().encode("utf-8")
    entries[f"{dist_info}/top_level.txt"] = (
        "\n".join(spec.packages) + "\n"
    ).encode("utf-8")
    license_path = ROOT / LICENSE_FILE
    if license_path.is_file():
        entries[f"{dist_info}/{LICENSE_FILE}"] = license_path.read_bytes()

    entries[f"{dist_info}/RECORD"] = render_record(entries, dist_info).encode("utf-8")
    return entries


def render_metadata(spec: WheelSpec, version: str) -> str:
    """``METADATA`` from the same values the package is built with."""
    lines = [
        "Metadata-Version: 2.1",
        f"Name: {spec.distribution}",
        f"Version: {version}",
        f"Summary: {spec.summary}",
        "Requires-Python: >=3.10,<3.11",
    ]
    if (ROOT / LICENSE_FILE).is_file():
        lines.append(f"License-File: {LICENSE_FILE}")
    lines.extend(f"Requires-Dist: {requirement}" for requirement in spec.requires_dist)
    return "\n".join(lines) + "\n"


def render_wheel_metadata() -> str:
    return "\n".join(
        [
            "Wheel-Version: 1.0",
            f"Generator: {GENERATOR}",
            "Root-Is-Purelib: true",
            "Tag: py3-none-any",
        ]
    ) + "\n"


def render_record(entries: dict[str, bytes], dist_info: str) -> str:
    """``RECORD``: one sha256 line per file, the record of itself left blank."""
    record_path = f"{dist_info}/RECORD"
    lines = [
        f"{path},{_record_hash(content)},{len(content)}"
        for path, content in sorted(entries.items())
    ]
    lines.append(f"{record_path},,")
    return "\n".join(lines) + "\n"


def write_wheel(spec: WheelSpec, version: str) -> tuple[Path, int]:
    """Write the wheel; return its path and how many files went in."""
    entries = collect_archive_entries(spec, version)
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    target = DIST_DIR / f"{spec.distribution}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for archive_path in sorted(entries):
            info = zipfile.ZipInfo(archive_path, date_time=ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, entries[archive_path])
    return target, len(entries)


def main() -> int:
    version = read_project_version()
    framework, game_layer = build_specs(version)
    for spec in (framework, game_layer):
        target, file_count = write_wheel(spec, version)
        size_mb = target.stat().st_size / 1024 / 1024
        print(f"  {target.relative_to(ROOT)}  ({file_count} 个文件, {size_mb:.1f} MB)")
    print()
    print("安装（按顺序，或让解析器在同一个目录里找）：")
    print(f"  uv pip install --python .venv\\Scripts\\python.exe {DIST_DIR.relative_to(ROOT)}\\autoscriptor-{version}-py3-none-any.whl")
    print(f"  uv pip install --python .venv\\Scripts\\python.exe {DIST_DIR.relative_to(ROOT)}\\zmxyol-{version}-py3-none-any.whl")
    return 0


def _project_table() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    if "[project]" not in text:
        raise SystemExit("pyproject.toml 里没有 [project] 段")
    return text.split("[project]", 1)[1]


def _collect_package_files(package: str) -> dict[str, bytes]:
    package_dir = ROOT / package
    if not package_dir.is_dir():
        raise SystemExit(f"找不到包目录: {package_dir}")
    files: dict[str, bytes] = {}
    for path in sorted(package_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if EXCLUDED_DIRECTORY_NAMES.intersection(relative.parts):
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        files[relative.as_posix()] = path.read_bytes()
    return files


def _record_hash(content: bytes) -> str:
    digest = hashlib.sha256(content).digest()
    return "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


if __name__ == "__main__":
    raise SystemExit(main())
