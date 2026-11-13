"""Parser registry for the scraping plugin.

The registry maps a short parser name (as used in the ``scraping_sites.yaml`` file) to the
concrete :class:`~src.collection.plugins.scraping.parsers.base.Parser` implementation.
"""

from importlib import import_module
from typing import Dict, Type

from .base import Parser

# Simple registry – keys are parser names, values are the concrete classes.
_PARSER_REGISTRY: Dict[str, Type[Parser]] = {}

def register(name: str, parser_cls: Type[Parser]) -> None:
    """Register *parser_cls* under *name*.

    This is called by each parser module at import time.
    """
    _PARSER_REGISTRY[name] = parser_cls

def get_parser(name: str) -> Parser:
    """Return an instance of the parser registered as *name*.

    Raises:
        ValueError: if *name* is not present in the registry.
    """
    if name not in _PARSER_REGISTRY:
        raise ValueError(f"Unknown parser name: '{name}'. Available parsers: {list(_PARSER_REGISTRY)}")
    return _PARSER_REGISTRY[name]()

# Auto‑import known parser modules so they register themselves.
for _mod in ["hackernews"]:
    try:
        import_module(f"src.collection.plugins.scraping.parsers.{_mod}")
    except Exception:  # pragma: no cover – import failures will surface in tests
        pass

