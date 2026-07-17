"""Static localization and HACS metadata checks."""

import json
from pathlib import Path


def test_translations_have_required_sections() -> None:
    """English and Polish include flows, sensors, actions, and action errors."""
    root = Path("custom_components/youtube_audio_downloader")
    strings = json.loads((root / "strings.json").read_text(encoding="utf-8"))
    for language in ("en", "pl"):
        translated = json.loads(
            (root / "translations" / f"{language}.json").read_text(encoding="utf-8")
        )
        assert translated.keys() == strings.keys()
        assert {"download", "download_batch"} <= translated["services"].keys()
        assert {"queue_length", "current_state", "progress"} <= translated["entity"][
            "sensor"
        ].keys()
        assert "queue_full" in translated["exceptions"]


def test_hacs_minimum_version_and_brand_assets() -> None:
    """HACS metadata pins HA 2026.7 and both source brand assets are present."""
    hacs = json.loads(Path("hacs.json").read_text(encoding="utf-8"))
    assert hacs["homeassistant"] == "2026.7.0"
    brand = Path("custom_components/youtube_audio_downloader/brand")
    assert (brand / "icon.png").stat().st_size > 0
    assert (brand / "logo.png").stat().st_size > 0
