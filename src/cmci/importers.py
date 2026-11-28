"""Tabular importers for CSV, JSON, and Excel workbooks.

Readers return a list of column-name -> raw cell value dictionaries. Turning
those into governed observations is the ingestion service's job.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SUPPORTED_FORMATS = ("csv", "json", "xlsx")


class ImportFailure(ValueError):
    """Raised when an input file cannot be parsed or mapped."""


@dataclass(frozen=True, slots=True)
class ColumnMapping:
    """Maps source columns onto CMCI observation fields."""

    period_start: str
    value: str
    period_end: str | None = None
    release_time: str | None = None
    vintage_time: str | None = None
    available_time: str | None = None
    available_time_precision: str | None = None
    available_time_method: str | None = None
    value_text: str | None = None
    unit: str | None = None
    timezone: str | None = None


def detect_format(path: str | Path) -> str:
    suffix = Path(path).suffix.lower().lstrip(".")
    if suffix == "xls":
        raise ImportFailure("不支持旧版 .xls，请另存为 .xlsx 后导入")
    if suffix not in SUPPORTED_FORMATS:
        raise ImportFailure(f"不支持的文件格式: .{suffix}；支持 {', '.join(SUPPORTED_FORMATS)}")
    return suffix


def read_rows(data: bytes, fmt: str) -> list[dict[str, Any]]:
    if fmt == "csv":
        return _read_csv(data)
    if fmt == "json":
        return _read_json(data)
    if fmt == "xlsx":
        return _read_xlsx(data)
    raise ImportFailure(f"不支持的文件格式: {fmt}")


def map_rows(rows: list[dict[str, Any]], mapping: ColumnMapping) -> list[dict[str, Any]]:
    mapped: list[dict[str, Any]] = []
    for row in rows:
        mapped.append(
            {
                "period_start": _pick(row, mapping.period_start, required=True),
                "period_end": _pick(row, mapping.period_end),
                "value": _pick(row, mapping.value, required=True),
                "release_time": _pick(row, mapping.release_time),
                "vintage_time": _pick(row, mapping.vintage_time),
                "available_time": _pick(row, mapping.available_time),
                "available_time_precision": _pick(row, mapping.available_time_precision),
                "available_time_method": _pick(row, mapping.available_time_method),
                "value_text": _pick(row, mapping.value_text),
                "unit": _pick(row, mapping.unit),
                "timezone": _pick(row, mapping.timezone),
            }
        )
    return mapped


def _pick(row: dict[str, Any], column: str | None, *, required: bool = False) -> Any:
    if column is None:
        if required:
            raise ImportFailure("必须提供列映射")
        return None
    if column not in row:
        if required:
            raise ImportFailure(f"源文件缺少列: {column}")
        return None
    return row[column]


def _read_csv(data: bytes) -> list[dict[str, Any]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportFailure("CSV 必须使用 UTF-8 编码") from exc
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ImportFailure("CSV 缺少表头")
    rows: list[dict[str, Any]] = []
    for row in reader:
        cleaned = {(key or "").strip(): value for key, value in row.items()}
        if any(value not in (None, "") for value in cleaned.values()):
            rows.append(cleaned)
    return rows


def _read_json(data: bytes) -> list[dict[str, Any]]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ImportFailure(f"JSON 解析失败: {exc}") from exc
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        payload = payload["data"]
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ImportFailure("JSON 必须是对象数组，或包含 data 数组的对象")
    return payload


def _read_xlsx(data: bytes) -> list[dict[str, Any]]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - dependency declared in pyproject
        raise ImportFailure("Excel 导入需要 openpyxl") from exc

    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        sheet = workbook.active
        iterator = sheet.iter_rows(values_only=True)
        try:
            header = next(iterator)
        except StopIteration:
            raise ImportFailure("Excel 缺少表头") from None
        columns = [str(cell).strip() if cell is not None else "" for cell in header]
        rows: list[dict[str, Any]] = []
        for values in iterator:
            if values is None or all(cell is None for cell in values):
                continue
            rows.append(
                {columns[index]: value for index, value in enumerate(values) if index < len(columns)}
            )
        return rows
    finally:
        workbook.close()