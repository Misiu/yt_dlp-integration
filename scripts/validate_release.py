"""Validate that a release tag matches the integration manifest version."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    _REPOSITORY_ROOT
    / "custom_components"
    / "youtube_audio_downloader"
    / "manifest.json"
)
_SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


class ReleaseValidationError(ValueError):
    """A tag or manifest cannot be used to create a release."""


def validate_release(tag: str, manifest_path: Path = DEFAULT_MANIFEST) -> str:
    """Return the normalized version when tag and manifest are consistent."""
    version = tag.removeprefix("v")
    if not _SEMVER_PATTERN.fullmatch(version):
        message = f"tag {tag!r} is not a supported semantic version"
        raise ReleaseValidationError(message)
    version_without_build = version.split("+", maxsplit=1)[0]
    if "-" in version_without_build:
        prerelease = version_without_build.split("-", maxsplit=1)[1]
        if any(
            identifier.startswith("0") and len(identifier) > 1
            for identifier in prerelease.split(".")
            if identifier.isdigit()
        ):
            message = (
                f"tag {tag!r} is not a supported semantic version: "
                "a numeric prerelease identifier has a leading zero"
            )
            raise ReleaseValidationError(message)

    try:
        manifest: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as err:
        message = f"cannot read {manifest_path}: {err}"
        raise ReleaseValidationError(message) from err
    except json.JSONDecodeError as err:
        message = f"invalid JSON in {manifest_path}: {err}"
        raise ReleaseValidationError(message) from err

    if not isinstance(manifest, dict) or not isinstance(
        manifest_version := manifest.get("version"), str
    ):
        raise ReleaseValidationError("manifest.json has no string version field")
    if manifest_version != version:
        message = (
            f"tag version {version!r} does not match manifest version "
            f"{manifest_version!r}"
        )
        raise ReleaseValidationError(message)
    return version


def main(argv: list[str] | None = None) -> int:
    """Run release validation from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="Release tag, for example 1.2.3 or v1.2.3")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Path to the integration manifest",
    )
    args = parser.parse_args(argv)
    try:
        version = validate_release(args.tag, args.manifest)
    except ReleaseValidationError as err:
        sys.stderr.write(f"Release validation failed: {err}\n")
        return 1
    sys.stdout.write(f"{version}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
