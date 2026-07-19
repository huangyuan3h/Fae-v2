"""Voice / text pipeline package.

Import submodules directly (e.g. ``fae.pipecat.bot``) — this package root
stays import-light so FastAPI can boot without pulling Daily/TTS stacks
until those paths are used.
"""

from __future__ import annotations

__all__: list[str] = []
