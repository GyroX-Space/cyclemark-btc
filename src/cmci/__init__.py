"""CMCI research data infrastructure.

Main line of this repository. CycleMark BTC (``cyclemark``) remains a
sub-product and is unaffected by this package.
"""

from .db import Database
from .importers import ColumnMapping, detect_format, map_rows, read_rows
from .ingestion import IngestionResult, IngestionService
from .models import DataSource, Indicator, IndicatorSourceLink, IndicatorVersion, OperationLog
from .registry import Registry

__all__ = [
    "ColumnMapping",
    "Database",
    "DataSource",
    "Indicator",
    "IndicatorSourceLink",
    "IndicatorVersion",
    "IngestionResult",
    "IngestionService",
    "OperationLog",
    "Registry",
    "detect_format",
    "map_rows",
    "read_rows",
]
__version__ = "0.2.0"