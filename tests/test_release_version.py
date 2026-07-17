"""Tests for automated release version validation."""

import json

import pytest

from scripts.validate_release import ReleaseValidationError, validate_release


def write_manifest(tmp_path, version):
    """Write a minimal manifest and return its path."""
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"version": version}), encoding="utf-8")
    return manifest


@pytest.mark.parametrize("tag", ["1.2.3", "v1.2.3"])
def test_release_tag_matches_manifest(tmp_path, tag) -> None:
    """Plain and v-prefixed tags normalize to the manifest version."""
    assert validate_release(tag, write_manifest(tmp_path, "1.2.3")) == "1.2.3"


def test_prerelease_tag_matches_manifest(tmp_path) -> None:
    """SemVer prerelease identifiers remain part of the normalized version."""
    version = "2.0.0-beta.1"
    assert validate_release(f"v{version}", write_manifest(tmp_path, version)) == version


def test_release_tag_must_match_manifest(tmp_path) -> None:
    """A mismatched tag blocks release creation."""
    with pytest.raises(ReleaseValidationError, match="does not match"):
        validate_release("1.2.4", write_manifest(tmp_path, "1.2.3"))


@pytest.mark.parametrize("tag", ["release-1.2.3", "1.2", "01.2.3", "1.2.3-01"])
def test_release_tag_must_be_semver(tmp_path, tag) -> None:
    """Non-SemVer tags are rejected before release creation."""
    with pytest.raises(ReleaseValidationError, match="semantic version"):
        validate_release(tag, write_manifest(tmp_path, "1.2.3"))
