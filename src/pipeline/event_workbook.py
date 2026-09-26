"""Export the canonical event CSV to the five analyst-facing Excel sheets."""

from __future__ import annotations

import csv
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from .event_csv import CSV_COLUMNS


SHEET_ORDER = ("all", "football", "concert", "festival", "exhibition", "other")
WORKBOOK_COLUMNS = CSV_COLUMNS
DEFAULT_RULES: dict[str, dict[str, tuple[str, ...]]] = {
    "football": {"type_values": ("football",), "keywords": ()},
    "concert": {
        "type_values": ("concert", "music_concert"),
        "keywords": (
            "concert",
            "live show",
            "liveshow",
            "am nhac",
            "music",
            "son tung",
            "hoa minzy",
            "anh trai say hi",
            "am thanh vuot dai duong",
        ),
    },
    "festival": {
        "type_values": ("festival", "festival_public"),
        "keywords": ("le hoi", "festival", "ngay hoi", "carnival"),
    },
    "exhibition": {
        "type_values": ("exhibition",),
        "keywords": ("trien lam", "trung bay", "exhibition"),
    },
    "other": {"type_values": (), "keywords": ()},
}


class EventWorkbookExporter:
    """Build a stable five-sheet workbook from the canonical event CSV."""

    def __init__(
        self,
        data_dir: str | Path,
        output_file: str = "event.xlsx",
        classification: Mapping[str, Any] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        relative_output = Path(output_file)
        if relative_output.is_absolute() or ".." in relative_output.parts:
            raise ValueError("events.workbook_output_file must stay inside data.")
        if relative_output.suffix.lower() != ".xlsx":
            raise ValueError("events.workbook_output_file must end in .xlsx.")
        self.input_path = self.data_dir / "event.csv"
        self.output_path = self.data_dir / relative_output
        self.rules = self._parse_rules(classification)

    def export(self) -> dict[str, Any]:
        all_rows = self._read_csv_rows()
        grouped_rows = {sheet: [] for sheet in SHEET_ORDER}
        grouped_rows["all"] = all_rows
        for row in all_rows:
            grouped_rows[self._sheet_for(row)].append(row)

        workbook = Workbook()
        workbook.remove(workbook.active)
        for sheet_name in SHEET_ORDER:
            worksheet = workbook.create_sheet(sheet_name)
            worksheet.append(WORKBOOK_COLUMNS)
            for row in grouped_rows[sheet_name]:
                worksheet.append([row.get(column, "") for column in WORKBOOK_COLUMNS])
            self._format_sheet(worksheet)

        self._atomic_save(workbook)
        return {
            "path": self.output_path.relative_to(self.data_dir).as_posix(),
            "sheets": {name: len(rows) for name, rows in grouped_rows.items()},
        }

    def _read_csv_rows(self) -> list[dict[str, str]]:
        if not self.input_path.exists():
            return []
        with self.input_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != CSV_COLUMNS:
                raise ValueError(
                    "events.csv columns do not match the event workbook contract."
                )
            return [
                {column: str(row.get(column) or "") for column in CSV_COLUMNS}
                for row in reader
            ]

    def _sheet_for(self, row: Mapping[str, str]) -> str:
        normalized_type = self._normalize(row.get("type", ""))
        search_text = self._normalize(
            " ".join((row.get("event_name", ""), row.get("type", "")))
        )
        for sheet_name in SHEET_ORDER:
            if sheet_name in {"all", "other"}:
                continue
            rule = self.rules[sheet_name]
            if normalized_type in rule["type_values"]:
                return sheet_name
            if any(keyword in search_text for keyword in rule["keywords"]):
                return sheet_name
        return "other"

    def _parse_rules(
        self,
        configured: Mapping[str, Any] | None,
    ) -> dict[str, dict[str, tuple[str, ...]]]:
        if configured is not None and not isinstance(configured, Mapping):
            raise ValueError("events.sheet_classification must be a mapping.")

        rules: dict[str, dict[str, tuple[str, ...]]] = {}
        for sheet_name in SHEET_ORDER:
            if sheet_name == "all":
                continue
            defaults = DEFAULT_RULES[sheet_name]
            source = configured.get(sheet_name, {}) if configured else {}
            if not isinstance(source, Mapping):
                raise ValueError(
                    f"events.sheet_classification.{sheet_name} must be a mapping."
                )
            rules[sheet_name] = {
                "type_values": self._rule_values(
                    source.get("type_values", defaults["type_values"]),
                    f"{sheet_name}.type_values",
                ),
                "keywords": self._rule_values(
                    source.get("keywords", defaults["keywords"]),
                    f"{sheet_name}.keywords",
                ),
            }
        return rules

    def _rule_values(self, value: object, label: str) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"events.sheet_classification.{label} must be a list.")
        normalized = tuple(
            self._normalize(item)
            for item in value
            if isinstance(item, str) and self._normalize(item)
        )
        if len(normalized) != len(value):
            raise ValueError(
                f"events.sheet_classification.{label} must contain non-empty strings."
            )
        return normalized

    @staticmethod
    def _normalize(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value.casefold().replace("đ", "d"))
        normalized = "".join(
            character
            for character in normalized
            if not unicodedata.combining(character)
        )
        return re.sub(r"\s+", " ", normalized).strip()

    @staticmethod
    def _format_sheet(worksheet: Any) -> None:
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = f"A1:{get_column_letter(len(WORKBOOK_COLUMNS))}1"
        for cell in worksheet[1]:
            cell.font = Font(bold=True)
        for column_index, column_name in enumerate(WORKBOOK_COLUMNS, start=1):
            longest = max(
                len(str(worksheet.cell(row=row, column=column_index).value or ""))
                for row in range(1, worksheet.max_row + 1)
            )
            maximum = 80 if column_name.endswith("source_url") else 48
            worksheet.column_dimensions[
                get_column_letter(column_index)
            ].width = min(max(longest + 2, 12), maximum)
    def _atomic_save(self, workbook: Workbook) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.output_path.with_suffix(".tmp.xlsx")
        try:
            workbook.save(temporary_path)
            os.replace(temporary_path, self.output_path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
