"""Run veraPDF in batch and return merged MRR XML.

This module manages the subprocess boundary: it builds a veraPDF CLI invocation,
splits long path lists into multiple runs when needed (Windows argv limits), and
merges the resulting XML fragments into one document for parsing.
"""

from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional, TextIO


# Conservative limit for Windows CreateProcess command-line length.
_SAFE_ARGV_CHARS = 7000


def _argv_char_estimate(args: List[str]) -> int:
    """Estimate command-line length for argv chunking."""
    if not args:
        return 0
    return sum(len(a) for a in args) + len(args) - 1


def _chunk_paths_for_argv(base_args: List[str], pdf_paths: List[str]) -> List[List[str]]:
    """Split PDF paths so each subprocess argv stays under the budget.

    The implementation is greedy and preserves input order.
    """
    if not pdf_paths:
        return []
    chunks: List[List[str]] = []
    i = 0
    n = len(pdf_paths)
    while i < n:
        chunk: List[str] = []
        while i < n:
            candidate = base_args + chunk + [pdf_paths[i]]
            if _argv_char_estimate(candidate) <= _SAFE_ARGV_CHARS:
                chunk.append(pdf_paths[i])
                i += 1
            elif not chunk:
                chunk.append(pdf_paths[i])
                i += 1
                break
            else:
                break
        chunks.append(chunk)
    return chunks


def _merge_job_xml_fragments(xml_strings: List[str]) -> str:
    """Merge multiple MRR XML fragments by concatenating ``<job>`` elements.

    This allows downstream parsing to treat chunked runs as a single logical report.
    """
    if not xml_strings:
        return '<?xml version="1.0" encoding="utf-8"?><report><jobs></jobs></report>'
    if len(xml_strings) == 1:
        return xml_strings[0]

    first = ET.fromstring(xml_strings[0])
    jobs_el = first.find("jobs")
    if jobs_el is None:
        jobs_el = ET.SubElement(first, "jobs")

    for extra in xml_strings[1:]:
        root = ET.fromstring(extra)
        other = root.find("jobs")
        if other is None:
            continue
        for job in list(other):
            jobs_el.append(job)

    raw = ET.tostring(first, encoding="utf-8")
    return raw.decode("utf-8")


class VeraPDFRunner:
    """Execute veraPDF over many PDFs and return combined MRR XML."""

    def __init__(
        self,
        verapdf_path: str,
        max_processes: int,
        disable_error_messages: bool = False,
        timeout_seconds: Optional[float] = None,
        stderr_log_path: Optional[str] = None,
    ) -> None:
        self.verapdf_path = str(Path(verapdf_path))
        self.max_processes = max(1, int(max_processes))
        self.disable_error_messages = disable_error_messages
        self.timeout_seconds = timeout_seconds
        self.stderr_log_path = stderr_log_path

    def _base_args(self) -> List[str]:
        """Build the fixed veraPDF CLI prefix shared by all chunks."""
        args = [
            self.verapdf_path,
            "-f",
            "ua1",
            "--success",
            "--format",
            "xml",
            "--processes",
            str(self.max_processes),
        ]
        if self.disable_error_messages:
            args.append("--disableerrormessages")
        return args

    def run_batch(self, pdf_paths: List[str]) -> str:
        """Run veraPDF on all paths and return merged MRR XML.

        Non-zero exit codes can still produce useful XML (for example, when PDFs
        fail validation), so stdout is parsed as long as it is non-empty.
        """
        if not pdf_paths:
            return '<?xml version="1.0" encoding="utf-8"?><report><jobs></jobs></report>'

        base = self._base_args()
        chunks = _chunk_paths_for_argv(base, pdf_paths)
        xml_parts: List[str] = []
        log_append = False

        for chunk in chunks:
            cmd = base + chunk
            stderr_file: Optional[TextIO] = None
            try:
                if self.stderr_log_path:
                    log_path = Path(self.stderr_log_path)
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    stderr_file = open(
                        log_path,
                        "a" if log_append else "w",
                        encoding="utf-8",
                        errors="replace",
                    )
                    log_append = True

                completed = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=stderr_file,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            finally:
                if stderr_file is not None:
                    stderr_file.close()

            # Non-zero exit can still accompany usable MRR XML when files fail validation.
            out = completed.stdout.decode("utf-8", errors="replace")
            if not out.strip():
                raise RuntimeError(
                    "veraPDF returned empty stdout. Check verapdf_path and stderr log: "
                    + (self.stderr_log_path or "(stderr not captured)")
                )
            xml_parts.append(out)

        return _merge_job_xml_fragments(xml_parts)
