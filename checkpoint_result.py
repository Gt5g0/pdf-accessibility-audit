"""Value type representing one veraPDF rule/check result for reporting.

This is the basic row-level unit used by the XML parser and the Excel writer.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CheckpointResult:
    """Outcome of one PDF/UA validation rule.

    Attributes:
        id: Composite identifier from veraPDF (specification/clause/testNumber) or a synthetic code.
        description: Human-readable description from veraPDF or a synthetic message.
        passed: True if the rule passed.
        failed_occurrences: Count of failed checks for this rule.
        failed_occurrence_pages: Optional comma-separated page hints for failures.
    """
    id: str
    description: str
    passed: bool
    failed_occurrences: int
    failed_occurrence_pages: str = ""
