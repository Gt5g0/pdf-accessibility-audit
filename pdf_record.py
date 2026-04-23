"""Value type describing a discovered PDF for validation and reporting.

``PDFRecord`` is the common output format of all scanners and the common input
format of the validation and reporting stages.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PDFRecord:
    """Metadata for one PDF selected for auditing.

    Attributes:
        name: Filename (basename) for display.
        student: First-level folder name under the scan root (may be empty).
        path: Absolute filesystem path to the PDF.
    """
    name: str
    student: str
    path: str
