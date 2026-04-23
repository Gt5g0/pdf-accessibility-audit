"""Local PDF discovery with optional first-level folder filtering.

This scanner treats the first directory segment under the root as the “student”
label used in reports. When ``scope.mode`` is ``students``, only those first-level
folders are included.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from pdf_record import PDFRecord


class LocalFileScanner:
    """Walk a root folder and return matching PDFs as ``PDFRecord`` rows."""

    def __init__(self, root_folder: str, scope: Optional[Dict[str, Any]] = None) -> None:
        self.root_folder = Path(root_folder).resolve()
        # Use explicit None check: ``{}`` is falsy but must not reset to "all" mode.
        self.scope = {"mode": "all", "students": []} if scope is None else scope

    def scan(self) -> List[PDFRecord]:
        """Enumerate ``*.pdf`` under the root and apply the configured scope filter.

        Returns an empty list if the root folder does not exist.
        """
        if not self.root_folder.is_dir():
            return []

        mode = str(self.scope.get("mode") or "all").strip().lower()
        raw_students = self.scope.get("students") or []
        if not isinstance(raw_students, list):
            raw_students = []

        students_filter: Set[str] | None = None
        if mode == "students":
            students_filter = {
                str(s).strip().lower() for s in raw_students if str(s).strip()
            }

        records: List[PDFRecord] = []
        for pdf_path in sorted(self.root_folder.rglob("*.pdf")):
            try:
                resolved = pdf_path.resolve()
                rel = resolved.relative_to(self.root_folder)
            except ValueError:
                continue

            parts = rel.parts
            if len(parts) >= 2:
                student = parts[0]
            else:
                student = ""

            if students_filter is not None:
                key = student.strip().lower() if student else ""
                if key not in students_filter:
                    continue

            records.append(
                PDFRecord(
                    name=parts[-1],
                    student=student,
                    path=str(resolved),
                )
            )

        return records
