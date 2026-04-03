import threading
from pathlib import Path
from typing import Any, Dict, Optional

from processing.ttl_parser import parse_ttl


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_TTL_PATH = ROOT_DIR / "unified_ontology.ttl"

_snapshot_lock = threading.Lock()
_parsed_snapshot: Optional[Dict[str, Any]] = None


def get_runtime_ontology_snapshot(force_refresh: bool = False) -> Dict[str, Any]:
    """Return the parsed ontology snapshot, preferring the local TTL file."""
    global _parsed_snapshot

    if not force_refresh and _parsed_snapshot is not None:
        return _parsed_snapshot

    with _snapshot_lock:
        if not force_refresh and _parsed_snapshot is not None:
            return _parsed_snapshot

        parsed = parse_ttl(str(DEFAULT_TTL_PATH))
        if "parse_error" in parsed:
            raise ValueError(f"Failed to parse runtime ontology TTL: {parsed['parse_error']}")

        _parsed_snapshot = parsed
        return _parsed_snapshot


def set_runtime_ontology_snapshot(parsed_data: Dict[str, Any]) -> Dict[str, Any]:
    """Override the shared parsed ontology snapshot with freshly uploaded data."""
    global _parsed_snapshot
    with _snapshot_lock:
        _parsed_snapshot = parsed_data
        return _parsed_snapshot


def clear_runtime_ontology_snapshot() -> None:
    """Clear the cached snapshot so the next access reparses the local TTL."""
    global _parsed_snapshot
    with _snapshot_lock:
        _parsed_snapshot = None
