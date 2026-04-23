"""Parse veraPDF MRR XML into structured per-file validation results.

This module converts the machine-readable report (MRR) XML emitted by veraPDF
into Python objects that are easy to summarize in Excel. It also emits synthetic
checkpoint rows when veraPDF output is missing or cannot be matched to an input
file, so problems are visible in the report instead of failing silently.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from checkpoint_result import CheckpointResult
from pdf_record import PDFRecord


def _normalize_path(path_str: str) -> str:
    """Return a normalized path string suitable for dictionary lookups.

    Uses ``Path.resolve`` when possible; falls back to ``normpath``/``normcase``
    for problematic inputs.
    """
    try:
        return str(Path(path_str).resolve())
    except (OSError, ValueError):
        return os.path.normcase(os.normpath(path_str))


def _build_record_indexes(
    records: List[PDFRecord], root_folder: str
) -> Tuple[Dict[str, PDFRecord], Dict[Tuple[str, str], PDFRecord]]:
    """Build lookup indexes to match veraPDF jobs back to scanned ``PDFRecord`` rows.

    Two indexes are maintained:
    - absolute-path based (fast path)
    - (student, relative path) based (fallback when paths are rewritten)
    """
    by_path: Dict[str, PDFRecord] = {}
    by_student_rel: Dict[Tuple[str, str], PDFRecord] = {}
    root = Path(root_folder).resolve()

    for rec in records:
        rp = _normalize_path(rec.path)
        by_path[rp] = rec
        if os.name == "nt":
            by_path[rp.lower()] = rec

        try:
            rel = Path(rec.path).resolve().relative_to(root)
            rel_key = rel.as_posix().lower()
        except ValueError:
            rel_key = Path(rec.path).name.lower()
        student_key = (rec.student or "").lower()
        by_student_rel[(student_key, rel_key)] = rec

    return by_path, by_student_rel


def _match_record(
    item_path: str,
    by_path: Dict[str, PDFRecord],
    by_student_rel: Dict[Tuple[str, str], PDFRecord],
    root_folder: str,
) -> Optional[PDFRecord]:
    """Match a veraPDF job path to a scanned ``PDFRecord`` using multiple strategies.

    Returns ``None`` when no match can be found; callers convert that into a
    synthetic “missing job” checkpoint for the affected file.
    """
    norm = _normalize_path(item_path)
    hit = by_path.get(norm)
    if hit:
        return hit
    if os.name == "nt":
        hit = by_path.get(norm.lower())
        if hit:
            return hit

    root = Path(root_folder).resolve()
    try:
        rel = Path(item_path).resolve().relative_to(root)
    except ValueError:
        return None

    student = rel.parts[0] if len(rel.parts) >= 2 else ""
    rel_key = rel.as_posix().lower()
    hit = by_student_rel.get((student.lower(), rel_key))
    if hit:
        return hit
    return None


_PAGE_INDEX_RE = re.compile(r"pages\[(\d+)\]", re.IGNORECASE)


def _pages_from_failed_node(el: ET.Element) -> Set[int]:
    """Best-effort extraction of 1-based page numbers from a failing node subtree.

    veraPDF failures can encode page hints in attributes or embedded text; this
    function uses simple heuristics to extract useful numbers for triage.
    """
    out: Set[int] = set()
    for k, v in el.attrib.items():
        if not v:
            continue
        lk = k.replace("-", "").replace("_", "").lower()
        if "page" not in lk:
            continue
        for part in re.split(r"[,;\s]+", str(v).strip()):
            if part.isdigit():
                out.add(int(part))

    blob = "".join(el.itertext())
    for m in _PAGE_INDEX_RE.finditer(blob):
        out.add(int(m.group(1)) + 1)
    for m in re.finditer(r"(?<![\w/])(?:page|pg\.?)\s*[:#]?\s*(\d+)", blob, re.IGNORECASE):
        out.add(int(m.group(1)))
    return out


def _failed_status(s: Optional[str]) -> bool:
    """Return True if the status value indicates failure (case-insensitive)."""
    return (s or "").strip().lower() == "failed"


def _collect_failed_pages_for_rule(rule: ET.Element) -> str:
    """Aggregate page hints for a failing rule into a comma-separated string."""
    pages: Set[int] = set()
    for node in rule.findall(".//check"):
        if _failed_status(node.get("status")):
            pages |= _pages_from_failed_node(node)
    for node in rule.findall(".//testAssertion"):
        if _failed_status(node.get("status")):
            pages |= _pages_from_failed_node(node)
    if not pages:
        return ""
    return ", ".join(str(p) for p in sorted(pages))


def _parse_rules(validation_report: ET.Element) -> List[CheckpointResult]:
    """Parse ``validationReport/details/rule`` elements into ``CheckpointResult`` rows.

    Each ``rule`` becomes one checkpoint row with a composite identifier and
    optional page hints when failing.
    """
    details = validation_report.find("details")
    if details is None:
        return []

    results: List[CheckpointResult] = []
    for rule in details.findall("rule"):
        status = (rule.get("status") or "").lower()
        passed = status == "passed"
        desc_el = rule.find("description")
        if desc_el is not None and len(desc_el):
            description = "".join(desc_el.itertext()).strip()
        elif desc_el is not None and desc_el.text:
            description = (desc_el.text or "").strip()
        else:
            description = ""

        failed_occurrences = int(rule.get("failedChecks") or 0)
        if failed_occurrences == 0 and not passed:
            failed_checks = rule.findall('.//check[@status="failed"]')
            failed_occurrences = len(failed_checks)

        pages_str = "" if passed else _collect_failed_pages_for_rule(rule)

        spec = rule.get("specification") or ""
        clause = rule.get("clause") or ""
        test_number = rule.get("testNumber") or ""
        parts = [p for p in (spec, clause, test_number) if p]
        cid = "|".join(parts) if parts else "unknown_rule"

        results.append(
            CheckpointResult(
                id=cid,
                description=description,
                passed=passed,
                failed_occurrences=failed_occurrences,
                failed_occurrence_pages=pages_str,
            )
        )
    return results


@dataclass
class ValidationReport:
    """Per-PDF validation result: overall outcome and checkpoint rows."""

    pdf_record: PDFRecord
    overall_pass: bool
    checkpoints: List[CheckpointResult] = field(default_factory=list)

    @staticmethod
    def parse_batch(
        xml_text: str,
        records: List[PDFRecord],
        root_folder: str,
    ) -> List["ValidationReport"]:
        """Parse merged MRR XML into a ``ValidationReport`` per scanned PDF record.

        The returned list is in the same order as ``records`` so the report aligns
        with the scan order.
        """
        by_path, by_student_rel = _build_record_indexes(records, root_folder)

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            return [
                ValidationReport(
                    rec,
                    overall_pass=False,
                    checkpoints=[
                        CheckpointResult(
                            id="XML_PARSE",
                            description=(
                                "Could not parse veraPDF output as XML: %s" % exc
                            ),
                            passed=False,
                            failed_occurrences=1,
                        )
                    ],
                )
                for rec in records
            ]

        jobs_el = root.find("jobs")
        if jobs_el is None:
            return ValidationReport._reports_for_missing_jobs(records)

        reports_by_path: Dict[str, ValidationReport] = {}
        for job in jobs_el.findall("job"):
            item = job.find("item")
            if item is None:
                continue
            name_el = item.find("name")
            if name_el is None or not name_el.text:
                continue
            item_path = name_el.text.strip()
            rec = _match_record(item_path, by_path, by_student_rel, root_folder)
            if rec is None:
                continue

            vr = job.find("validationReport")
            if vr is None:
                reports_by_path[rec.path] = ValidationReport(
                    rec,
                    overall_pass=False,
                    checkpoints=[
                        CheckpointResult(
                            id="NO_VALIDATION_REPORT",
                            description="veraPDF job contained no validationReport.",
                            passed=False,
                            failed_occurrences=1,
                        )
                    ],
                )
                continue

            compliant = (vr.get("isCompliant") or "").lower() == "true"
            checkpoints = _parse_rules(vr)
            details = vr.find("details")
            if not checkpoints and details is not None:
                passed_rules = int(details.get("passedRules") or 0)
                failed_rules = int(details.get("failedRules") or 0)
                if failed_rules == 0 and compliant and passed_rules > 0:
                    # All rules passed; veraPDF may omit individual rule rows.
                    checkpoints = [
                        CheckpointResult(
                            id="SUMMARY",
                            description=(
                                "All validation rules passed "
                                "(%d rules, checks per veraPDF summary)." % passed_rules
                            ),
                            passed=True,
                            failed_occurrences=0,
                        )
                    ]

            if checkpoints:
                overall_pass = compliant and all(c.passed for c in checkpoints)
            else:
                overall_pass = compliant

            reports_by_path[rec.path] = ValidationReport(
                rec,
                overall_pass=overall_pass,
                checkpoints=checkpoints,
            )

        ordered: List[ValidationReport] = []
        for rec in records:
            matched = reports_by_path.get(rec.path)
            if matched is None:
                ordered.append(
                    ValidationReport(
                        rec,
                        overall_pass=False,
                        checkpoints=[
                            CheckpointResult(
                                id="MISSING_JOB",
                                description=(
                                    "No veraPDF job output matched this file path "
                                    "after path normalization."
                                ),
                                passed=False,
                                failed_occurrences=1,
                            )
                        ],
                    )
                )
            else:
                ordered.append(matched)
        return ordered

    @staticmethod
    def _reports_for_missing_jobs(records: List[PDFRecord]) -> List["ValidationReport"]:
        """Return synthetic failures when the MRR document has no ``<jobs>`` element."""
        syn = CheckpointResult(
            id="NO_JOBS",
            description="veraPDF XML contained no jobs element.",
            passed=False,
            failed_occurrences=1,
        )
        return [
            ValidationReport(rec, overall_pass=False, checkpoints=[syn]) for rec in records
        ]
