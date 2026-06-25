"""Shared test fixtures."""

import pytest

from satviz import config


@pytest.fixture(autouse=True)
def isolate_output_root(tmp_path, monkeypatch):
    """Point OUTPUT_ROOT at a fresh temp dir so the run index and any default Storage
    never read or write the real output_images/ during tests."""
    monkeypatch.setattr(config, "OUTPUT_ROOT", str(tmp_path / "output"))
