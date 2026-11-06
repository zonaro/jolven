"""Backend-neutral capture contracts for Jolven.

This module intentionally has no GTK, OBS or GPU Screen Recorder dependency.
Adapters translate their native API into these capabilities and states.
No backend is started simply by importing this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


class CaptureFeature(str, Enum):
    RECORD = "record"
    REPLAY = "replay"
    SCREENSHOT = "screenshot"
    STREAM = "stream"
    SCENES = "scenes"
    AUDIO_MIXER = "audio_mixer"


class CaptureState(str, Enum):
    UNAVAILABLE = "unavailable"
    IDLE = "idle"
    STARTING = "starting"
    ACTIVE = "active"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass(frozen=True)
class CaptureCapabilities:
    """Capabilities discovered at runtime, never assumed from backend name."""

    backend_id: str
    features: frozenset[CaptureFeature]

    def supports(self, feature: CaptureFeature) -> bool:
        return feature in self.features


@dataclass(frozen=True)
class CaptureStatus:
    backend_id: str
    state: CaptureState
    feature: CaptureFeature
    error: str | None = None


class CaptureError(RuntimeError):
    """A capture operation failed without affecting the game session."""


class UnsupportedCaptureFeature(CaptureError):
    """The selected backend does not expose the requested operation."""


@runtime_checkable
class CaptureBackend(Protocol):
    """Synchronous contract; callers must keep blocking work off the GTK thread.

    The coordinator owns concurrency, state publication and lifecycle. Backends
    must not silently start another backend or log streaming credentials.
    """

    @property
    def backend_id(self) -> str: ...

    def detect_capabilities(self) -> CaptureCapabilities: ...

    def get_status(self, feature: CaptureFeature) -> CaptureStatus: ...

    def start(self, feature: CaptureFeature) -> None: ...

    def stop(self, feature: CaptureFeature) -> None: ...

    def save_replay(self) -> None: ...

    def close(self) -> None: ...
