"""Sensors for YouTube Audio Downloader."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import YoutubeAudioDownloaderConfigEntry
from .api import StatusData
from .const import CONF_INSTANCE_ID, DOMAIN, NAME, STATE_OPTIONS
from .coordinator import YoutubeAudioDownloaderCoordinator


@dataclass(frozen=True, kw_only=True)
class YoutubeAudioDownloaderSensorEntityDescription(SensorEntityDescription):
    """Describe a YouTube Audio Downloader sensor."""

    value_fn: Callable[[StatusData], str | int | float | None]


SENSORS: tuple[YoutubeAudioDownloaderSensorEntityDescription, ...] = (
    YoutubeAudioDownloaderSensorEntityDescription(
        key="queue_length",
        translation_key="queue_length",
        native_unit_of_measurement="jobs",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda status: status["queue_length"],
    ),
    YoutubeAudioDownloaderSensorEntityDescription(
        key="current_state",
        translation_key="current_state",
        device_class=SensorDeviceClass.ENUM,
        options=STATE_OPTIONS,
        value_fn=lambda status: status["state"],
    ),
    YoutubeAudioDownloaderSensorEntityDescription(
        key="progress",
        translation_key="progress",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda status: status["progress"],
    ),
)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: YoutubeAudioDownloaderConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up all sensors for one App service device."""
    async_add_entities(
        YoutubeAudioDownloaderSensor(entry, description) for description in SENSORS
    )


class YoutubeAudioDownloaderSensor(
    CoordinatorEntity[YoutubeAudioDownloaderCoordinator], SensorEntity
):
    """A coordinator-backed App sensor."""

    _attr_has_entity_name = True
    entity_description: YoutubeAudioDownloaderSensorEntityDescription

    def __init__(
        self,
        entry: YoutubeAudioDownloaderConfigEntry,
        description: YoutubeAudioDownloaderSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        coordinator = entry.runtime_data.coordinator
        super().__init__(coordinator)
        self.entity_description = description
        instance_id = entry.data[CONF_INSTANCE_ID]
        self._attr_unique_id = f"{instance_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, instance_id)},
            name=NAME,
            manufacturer="Misiu",
            model="Home Assistant App",
            sw_version=str(entry.runtime_data.info.get("version", "unknown")),
        )

    @property
    def native_value(self) -> str | int | float | None:
        """Return the latest value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose safe current-track context without the source URL."""
        if self.entity_description.key == "queue_length":
            return None
        current = self.coordinator.data.get("current")
        if current is None:
            return None
        artist = current.get("artist") or current.get("channel")
        attributes: dict[str, Any] = {
            "job_id": current.get("id"),
            "title": current.get("title") or current.get("source_title"),
            "artist": artist,
        }
        return {key: value for key, value in attributes.items() if value is not None}
