"""alloy-data-extractor — multi-vendor ETL pipeline for canonical
device YAML.  See ``README.md`` for the architecture overview.

Public surface re-exports the most-used helpers so consumers can
``from alloy_data_extractor import run_extraction, …`` without
worrying about submodule layout.
"""

from __future__ import annotations

from alloy_data_extractor.cli import main
from alloy_data_extractor.emit.canonical_yaml import write_device_yaml
from alloy_data_extractor.pipeline import run_extraction

__all__ = ["main", "run_extraction", "write_device_yaml"]
__version__ = "0.1.0"
