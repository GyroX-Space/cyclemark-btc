"""CMCI research data infrastructure.

Main line of this repository. CycleMark BTC (``cyclemark``) remains a
sub-product and is unaffected by this package.
"""

from .datasets import (
    PartitionConflict,
    PartitionConflictError,
    ResearchDatasetService,
)
from .db import Database
from .importers import ColumnMapping, detect_format, map_rows, read_rows
from .ingestion import IngestionResult, IngestionService
from .models import (
    DataSource,
    DatasetMember,
    DatasetVersion,
    Indicator,
    IndicatorSourceLink,
    IndicatorVersion,
    OperationLog,
    ReplayJob,
    ResearchDataset,
    ResearchProject,
)
from .registry import Registry
from .replay import ReplayResult, ReplayService

__all__ = [
    "ColumnMapping",
    "DataSource",
    "Database",
    "DatasetMember",
    "DatasetVersion",
    "Indicator",
    "IndicatorSourceLink",
    "IndicatorVersion",
    "IngestionResult",
    "IngestionService",
    "OperationLog",
    "PartitionConflict",
    "PartitionConflictError",
    "Registry",
    "ReplayJob",
    "ReplayResult",
    "ReplayService",
    "ResearchDataset",
    "ResearchDatasetService",
    "ResearchProject",
    "detect_format",
    "map_rows",
    "read_rows",
]
__version__ = "0.4.0"