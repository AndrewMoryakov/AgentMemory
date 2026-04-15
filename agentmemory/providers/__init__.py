from .base import BaseMemoryProvider
from .localjson import LocalJsonProvider


def __getattr__(name: str):
    if name == "Mem0Provider":
        from .mem0 import Mem0Provider
        return Mem0Provider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["BaseMemoryProvider", "LocalJsonProvider", "Mem0Provider"]
