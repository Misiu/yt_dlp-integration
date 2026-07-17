"""Shared pytest configuration."""

import pytest

pytest_plugins = ("pytest_homeassistant_custom_component",)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading this repository's custom component in every test."""
    return


def pytest_configure(config):
    """Register the custom integration marker environment."""
    config.addinivalue_line("markers", "enable_custom_integrations")
