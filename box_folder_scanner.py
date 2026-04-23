"""Scan a Box folder tree for PDFs and download them to a local staging directory.

Downloaded PDFs are written under a staging root so the rest of the pipeline can
operate on local filesystem paths (matching the local scanning mode).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from box_sdk_gen import BoxClient

from pdf_record import PDFRecord


def _entry_attr(entry: Any, key: str) -> Any:
    """Read attribute ``key`` from an SDK entry (object or dict)."""
    if entry is None:
        return None
    v = getattr(entry, key, None)
    if v is not None:
        return v
    if isinstance(entry, dict):
        return entry.get(key)
    return None


def _sanitize_segment(name: str) -> str:
    """Make a Box item name safe to use as a local path segment.

    This avoids illegal filename characters on Windows and reduces the chance of
    unexpected path behavior when mirroring Box names locally.
    """
    return re.sub(r'[/\\:*?"<>|]', "_", name).strip() or "_"


def clear_staging_directory(staging_dir: Path) -> None:
    """Remove all files and subfolders under ``staging_dir`` (keeps the root dir)."""
    root = Path(staging_dir).resolve()
    if not root.is_dir():
        return
    for child in root.iterdir():
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child, ignore_errors=True)


class BoxFolderScanner:
    """Recursively list PDFs under a Box folder ID and download them locally."""

    def __init__(
        self,
        client: BoxClient,
        root_folder_id: str,
        staging_dir: Path,
        scope: Optional[Dict[str, Any]] = None,
        clear_staging: bool = True,
    ) -> None:
        self._client = client
        self._root_folder_id = str(root_folder_id).strip()
        self._staging = Path(staging_dir).resolve()
        self._scope = {"mode": "all", "students": []} if scope is None else scope
        self._clear_staging = clear_staging

    def _students_filter(self) -> Optional[Set[str]]:
        """Return the normalized set of student folder names to include, or None for all."""
        mode = str(self._scope.get("mode") or "all").strip().lower()
        raw = self._scope.get("students") or []
        if mode != "students" or not isinstance(raw, list):
            return None
        return {str(s).strip().lower() for s in raw if str(s).strip()}

    def _clear_staging_dir(self) -> None:
        """Ensure staging exists and optionally clear prior contents."""
        self._staging.mkdir(parents=True, exist_ok=True)
        if self._clear_staging:
            clear_staging_directory(self._staging)

    def _iter_folder_items(self, folder_id: str) -> List[Any]:
        """Return all immediate children of a Box folder using marker-based pagination.

        Marker pagination avoids large-folder offset limits.
        """
        items: List[Any] = []
        limit = 1000
        marker: Optional[str] = None
        while True:
            page = self._client.folders.get_folder_items(
                folder_id,
                usemarker=True,
                marker=marker,
                limit=limit,
            )
            batch = list(page.entries or [])
            items.extend(batch)
            marker = page.next_marker
            if not marker:
                break
        return items

    def _download_file(self, file_id: str, dest: Path) -> None:
        """Download a Box file to ``dest`` on disk."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as out:
            self._client.downloads.download_file_to_output_stream(file_id, out)

    def _walk(
        self,
        folder_id: str,
        rel_parts: Tuple[str, ...],
        records: List[PDFRecord],
        students_filter: Optional[Set[str]],
    ) -> None:
        """Depth-first recursion over Box folders, appending ``PDFRecord`` rows for PDFs."""
        student = rel_parts[0] if rel_parts else ""
        if students_filter is not None:
            key = student.strip().lower() if student else ""
            if key not in students_filter:
                return

        for entry in self._iter_folder_items(folder_id):
            etype = _entry_attr(entry, "type")
            name = _entry_attr(entry, "name")
            eid = _entry_attr(entry, "id")
            if not name or not eid:
                continue
            if etype == "folder":
                sub = rel_parts + (_sanitize_segment(str(name)),)
                if students_filter is None or sub[0].strip().lower() in students_filter:
                    self._walk(str(eid), sub, records, students_filter)
                continue
            if etype != "file":
                continue
            if not str(name).lower().endswith(".pdf"):
                continue

            rel = rel_parts + (_sanitize_segment(str(name)),)
            local_rel = Path(*rel) if rel else Path(_sanitize_segment(str(name)))
            dest = self._staging / local_rel
            self._download_file(str(eid), dest)

            student_cell = rel_parts[0] if rel_parts else ""
            records.append(
                PDFRecord(
                    name=str(name),
                    student=student_cell,
                    path=str(dest.resolve()),
                )
            )

    def scan(self) -> List[PDFRecord]:
        """Download PDFs from the configured Box subtree and return ``PDFRecord`` rows."""
        if not self._root_folder_id:
            return []

        self._clear_staging_dir()
        students_filter = self._students_filter()
        records: List[PDFRecord] = []

        if students_filter is None:
            self._walk(self._root_folder_id, (), records, None)
        else:
            for entry in self._iter_folder_items(self._root_folder_id):
                etype = _entry_attr(entry, "type")
                name = _entry_attr(entry, "name")
                eid = _entry_attr(entry, "id")
                if etype != "folder" or not name or not eid:
                    continue
                key = str(name).strip().lower()
                if key not in students_filter:
                    continue
                self._walk(
                    str(eid),
                    (_sanitize_segment(str(name)),),
                    records,
                    students_filter,
                )

        records.sort(key=lambda r: (r.student.lower(), r.name.lower()))
        return records
