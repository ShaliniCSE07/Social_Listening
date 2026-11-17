import importlib
import pkgutil
from typing import Dict, List, Optional, Type

from src.collection.base import BaseConnector
from src.contracts.enums import Method
import src.collection.plugins as plugins_pkg


def get_all_connectors(plugins_path: Optional[List[str]] = None, prefix: Optional[str] = None) -> List[Type[BaseConnector]]:
    """Auto-discover all connectors under collection plugins directory."""
    connectors: List[Type[BaseConnector]] = []
    path = plugins_path if plugins_path is not None else plugins_pkg.__path__
    module_prefix = prefix if prefix is not None else f"{plugins_pkg.__name__}."

    for _, module_name, is_pkg in pkgutil.iter_modules(path, module_prefix):
        if is_pkg:
            try:
                mod = importlib.import_module(module_name)
                plugin_connectors = getattr(mod, "CONNECTORS", [])
                for conn in plugin_connectors:
                    if isinstance(conn, type) and issubclass(conn, BaseConnector):
                        connectors.append(conn)
            except Exception:
                continue

    return connectors


def get_connectors(method: Optional[Method] = None, plugins_path: Optional[List[str]] = None, prefix: Optional[str] = None) -> List[Type[BaseConnector]]:
    """Retrieve all connectors, optionally filtered by Method."""
    all_connectors = get_all_connectors(plugins_path=plugins_path, prefix=prefix)
    if method is None:
        return all_connectors
    return [c for c in all_connectors if getattr(c, "method", None) == method]


def get_connector(name: str, plugins_path: Optional[List[str]] = None, prefix: Optional[str] = None) -> Optional[Type[BaseConnector]]:
    """Retrieve a single connector by unique name."""
    for conn in get_all_connectors(plugins_path=plugins_path, prefix=prefix):
        if getattr(conn, "name", None) == name:
            return conn
    return None

