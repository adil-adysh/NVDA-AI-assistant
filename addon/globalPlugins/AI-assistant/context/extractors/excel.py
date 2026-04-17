# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from logHandler import log

from ...context.types import PageSnapshot, SnapshotType
from .base import BasePageExtractor
from .browser import BrowserAwarePageExtractor
from .candidate_base import ExtractionContext


class ExcelAwarePageExtractor(BasePageExtractor):
	"""Excel-specific page extraction.

	This extractor is intentionally separate from browser-specific extraction.
	It attempts to read Excel cell context first and falls back to browser
	extraction behavior for non-Excel scenarios.
	"""

	def extract(self):
		log.debug("ExcelAwarePageExtractor.extract: starting Excel-aware extraction")
		try:
			context = self._buildContext()
			if self._isExcelContext(context):
				excel_snapshot = self._buildExcelSnapshot(context.focus, context)
				if excel_snapshot is not None:
					log.debug("ExcelAwarePageExtractor.extract: Excel snapshot selected")
					return excel_snapshot
		except Exception:
			log.debug("ExcelAwarePageExtractor.extract: Excel extraction failed, falling back", exc_info=True)

		return BrowserAwarePageExtractor(self._nvda_context_provider).extract()

	def _isExcelContext(self, context: ExtractionContext) -> bool:
		if context.appName == "excel":
			return True
		focus = context.focus
		return focus is not None and getattr(focus, "excelCellInfo", None) is not None

	def _buildExcelSnapshot(self, obj: object | None, context: ExtractionContext) -> PageSnapshot | None:
		if obj is None:
			return None

		cell_info = getattr(obj, "excelCellInfo", None)
		if cell_info is None:
			return None

		extra_text = self._buildExcelContextText(obj, cell_info)
		if not extra_text:
			return None

		trimmed_text, truncated = self._trimText(extra_text)
		if not trimmed_text:
			return None

		title = self._buildExcelTitle(obj, cell_info, context)
		headings = self._buildExcelHeadings(obj, cell_info)

		return PageSnapshot(
			snapshot_type=SnapshotType.EXCEL,
			title=title or "Excel",
			appTitle=self._extractAppTitle(context),
			text=trimmed_text,
			truncated=truncated,
			headings=headings,
			links=(),
			buttons=(),
			landmarks=(),
		)

	def _buildExcelContextText(self, focus: object, cell_info: Any) -> str:
		lines: list[str] = []

		sheet_name = self._getExcelSheetName(cell_info)
		address = self._getExcelCellAddress(focus, cell_info)
		workbook_name = self._getExcelWorkbookName(focus)
		row_number = getattr(focus, "rowNumber", None)
		column_number = getattr(focus, "columnNumber", None)

		if workbook_name:
			lines.append(f"Workbook: {workbook_name}")
		if sheet_name:
			lines.append(f"Worksheet: {sheet_name}")
		if address:
			lines.append(f"Cell: {address}")
		elif isinstance(row_number, int) and isinstance(column_number, int):
			lines.append(f"Cell position: row {row_number}, column {column_number}")

		range_address = self._getExcelRangeAddress(cell_info, focus)
		if range_address and range_address != address:
			lines.append(f"Range: {range_address}")

		table_name = self._getExcelTableName(cell_info)
		if table_name:
			lines.append(f"Table: {table_name}")

		row_header, col_header = self._getExcelHeaders(cell_info)
		if row_header:
			lines.append(f"Row header: {row_header}")
		if col_header:
			lines.append(f"Column header: {col_header}")

		value_text = self._getExcelValueText(focus, cell_info)
		if value_text:
			lines.append(f"Value: {value_text}")

		formula = self._getExcelFormula(cell_info)
		if formula:
			lines.append(f"Formula: {formula}")

		note = self._getExcelNote(cell_info)
		if note:
			lines.append(f"Note: {note}")

		cell_type = self._getExcelCellType(cell_info)
		if cell_type:
			lines.append(f"Cell type: {cell_type}")

		return "\n".join(line for line in lines if line)

	def _getExcelValueText(self, focus: object, cell_info: Any) -> str:
		value = getattr(cell_info, "text", None)
		if isinstance(value, str) and value.strip():
			return value.strip()

		value = getattr(cell_info, "value", None)
		if isinstance(value, str) and value.strip():
			return value.strip()
		if value is not None:
			return str(value).strip()

		name = getattr(focus, "name", None)
		if isinstance(name, str) and name.strip():
			return name.strip()

		return self._extractText(focus).strip()

	def _getExcelFormula(self, cell_info: Any) -> str:
		formula = getattr(cell_info, "formula", None)
		if isinstance(formula, str) and formula.strip():
			return formula.strip()
		return ""

	def _getExcelNote(self, cell_info: Any) -> str:
		for attr in ("note", "comment", "cellComment", "commentText"):
			value = getattr(cell_info, attr, None)
			if isinstance(value, str) and value.strip():
				return value.strip()
		return ""

	def _getExcelCellType(self, cell_info: Any) -> str:
		for attr in ("cellType", "dataType", "type"):
			value = getattr(cell_info, attr, None)
			if isinstance(value, str) and value.strip():
				return value.strip()
		return ""

	def _getExcelSheetName(self, cell_info: Any) -> str:
		for attr in ("sheetName", "worksheet", "worksheetName", "sheetTitle", "sheet"):
			value = getattr(cell_info, attr, None)
			if isinstance(value, str) and value.strip():
				return value.strip()
		return ""

	def _getExcelWorkbookName(self, focus: object) -> str:
		for attr in ("windowText", "name", "title", "description"):
			value = getattr(focus, attr, None)
			if isinstance(value, str) and value.strip():
				return value.strip()
		return ""

	def _getExcelCellAddress(self, focus: object, cell_info: Any) -> str:
		address = getattr(cell_info, "address", None)
		if isinstance(address, str) and address.strip():
			return address.strip()

		row = getattr(focus, "rowNumber", None)
		col = getattr(focus, "columnNumber", None)
		if isinstance(row, int) and isinstance(col, int):
			return f"R{row}C{col}"

		return ""

	def _getExcelRangeAddress(self, cell_info: Any, focus: object) -> str:
		for attr in ("rangeAddress", "range", "selectedRange", "selectionRange", "activeRange", "cellRange"):
			value = getattr(cell_info, attr, None)
			result = self._normalizeExcelText(value)
			if result:
				return result
		return self._getExcelCellAddress(focus, cell_info)

	def _getExcelTableName(self, cell_info: Any) -> str:
		for attr in ("tableName", "tableTitle", "table", "listObjectName", "listName"):
			value = getattr(cell_info, attr, None)
			result = self._normalizeExcelText(value)
			if result:
				return result
		return ""

	def _getExcelHeaders(self, cell_info: Any) -> tuple[str, str]:
		row_header = self._probeExcelHeader(cell_info, (
			"rowHeader",
			"rowHeaders",
			"rowHeaderText",
			"rowHeaderLabels",
			"rowHeaderCells",
			"rowHeadersText",
		))
		column_header = self._probeExcelHeader(cell_info, (
			"columnHeader",
			"columnHeaders",
			"columnHeaderText",
			"columnHeaderLabels",
			"columnHeaderCells",
			"columnHeadersText",
		))
		return row_header, column_header

	def _probeExcelHeader(self, cell_info: Any, attrs: tuple[str, ...]) -> str:
		for attr in attrs:
			value = getattr(cell_info, attr, None)
			if value is None:
				continue
			if isinstance(value, str) and value.strip():
				return value.strip()
			if isinstance(value, (list, tuple)):
				parts = [self._normalizeExcelText(item) for item in value if self._normalizeExcelText(item)]
				if parts:
					return "; ".join(parts)
			try:
				return str(value).strip()
			except Exception:
				continue
		return ""

	def _normalizeExcelText(self, value: Any) -> str:
		if isinstance(value, str) and value.strip():
			return value.strip()
		if isinstance(value, (int, float)):
			return str(value)
		if isinstance(value, (list, tuple)):
			parts = [self._normalizeExcelText(item) for item in value]
			return "; ".join(part for part in parts if part)
		return ""

	def _buildExcelTitle(self, focus: object, cell_info: Any, context: ExtractionContext) -> str:
		parts: list[str] = []
		workbook_name = self._getExcelWorkbookName(focus)
		sheet_name = self._getExcelSheetName(cell_info)
		address = self._getExcelCellAddress(focus, cell_info)

		if workbook_name:
			parts.append(workbook_name)
		if sheet_name and address:
			parts.append(f"{sheet_name}!{address}")
		elif sheet_name:
			parts.append(sheet_name)
		elif address:
			parts.append(address)

		if parts:
			return " - ".join(parts)

		return self._extractTitle(focus, context)

	def _buildExcelHeadings(self, focus: object, cell_info: Any) -> tuple[tuple[int | None, str], ...]:
		sheet_name = self._getExcelSheetName(cell_info)
		address = self._getExcelCellAddress(focus, cell_info)
		row_header, column_header = self._getExcelHeaders(cell_info)
		table_name = self._getExcelTableName(cell_info)
		headings: list[tuple[int | None, str]] = []
		if sheet_name and address:
			headings.append((None, f"{sheet_name}!{address}"))
		elif sheet_name:
			headings.append((None, sheet_name))
		elif address:
			headings.append((None, address))
		if row_header:
			headings.append((None, f"Row header: {row_header}"))
		if column_header:
			headings.append((None, f"Column header: {column_header}"))
		if table_name:
			headings.append((None, f"Table: {table_name}"))
		return tuple(headings)
