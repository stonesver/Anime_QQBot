"""Fake AstrBot objects for unit tests (Task 8).

These fakes exercise the plugin lifecycle and metadata without importing
the AstrBot SDK. All data held in memory.
"""

from __future__ import annotations


class FakeContext:
    """Minimal Context stand-in that holds setattr values."""

    pass


__all__ = ["FakeContext"]
