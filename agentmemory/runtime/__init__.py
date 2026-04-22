from __future__ import annotations


def runtime_info():
    from .config import runtime_info as _runtime_info

    return _runtime_info()


__all__ = ["runtime_info"]
