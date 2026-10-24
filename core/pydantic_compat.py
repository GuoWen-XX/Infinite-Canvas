"""Pydantic v1 / v2 compatibility utilities."""
from typing import Any

def dump_pydantic(obj: Any, *args: Any, **kwargs: Any) -> Any:
    """Dump pydantic model safely using model_dump (v2) with fallback to dict (v1)."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump(*args, **kwargs)
    if hasattr(obj, "dict"):
        return obj.dict(*args, **kwargs)
    return dict(obj) if isinstance(obj, dict) else obj
