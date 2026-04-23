"""End-to-end orchestration for the PDF accessibility audit pipeline.

This module is the CLI-facing “composition root”: it loads configuration, selects
the ingestion strategy (local vs. Box), runs veraPDF, parses results, and writes
the Excel workbook.
"""

from __future__ import annotations

import os
from datetime import datetime
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from local_file_scanner import LocalFileScanner
from validation_report import ValidationReport
from report_builder import ReportBuilder
from verapdf_runner import VeraPDFRunner


def resolve_verapdf_path(raw: Any) -> Path:
    """Resolve the veraPDF CLI path from config (explicit path or auto-discovery).

    Accepts a concrete filesystem path, or ``auto`` / empty / None to search
    ``PATH`` and common Windows install locations.

    Raises:
        FileNotFoundError: If the executable cannot be found or the explicit path
            does not exist.
    """
    if raw is None:
        s = ""
    else:
        s = str(raw).strip()
    if s.lower() in ("", "auto"):
        for name in ("verapdf.bat", "verapdf"):
            found = shutil.which(name)
            if found:
                p = Path(found)
                if p.is_file():
                    return p
        candidates = [
            Path(r"C:\Program Files\veraPDF\verapdf.bat"),
            Path(r"C:\Program Files (x86)\veraPDF\verapdf.bat"),
            Path.home() / "verapdf" / "verapdf.bat",
        ]
        la = os.environ.get("LOCALAPPDATA")
        if la:
            candidates.append(Path(la) / "veraPDF" / "verapdf.bat")
        for c in candidates:
            if c.is_file():
                return c
        raise FileNotFoundError(
            "Could not find veraPDF. Install veraPDF, add it to PATH, or set "
            "verapdf_path in config.yaml to the full path of verapdf.bat (Windows) "
            "or the verapdf script (Unix)."
        )
    p = Path(s)
    if not p.is_file():
        raise FileNotFoundError("verapdf_path is not a file: %s" % p)
    return p


def merge_scope_students_from_root(cfg: Dict[str, Any]) -> None:
    """If ``students`` is at YAML root, copy it under ``scope``.

    This is a small robustness feature to recover from common YAML indentation
    mistakes where ``students`` ends up at the top level instead of nested under
    ``scope``.
    """
    scope = cfg.get("scope")
    if not isinstance(scope, dict):
        return
    if scope.get("students") is not None:
        return
    root = cfg.get("students")
    if root is None:
        return
    scope["students"] = root


class AuditPipeline:
    """End-to-end PDF/UA-1 audit: config, scan, validate, parse, and report."""

    def __init__(self, config_path: str) -> None:
        self.config_path = Path(config_path)

    def load_config(self) -> Dict[str, Any]:
        """Read and parse the YAML configuration file.

        Raises:
            FileNotFoundError: If the config path does not exist.
            ValueError: If the YAML does not decode to a mapping.
        """
        if not self.config_path.is_file():
            raise FileNotFoundError("Config not found: %s" % self.config_path)
        with open(self.config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError("config.yaml must contain a mapping at the top level.")
        return data

    @staticmethod
    def validate_config(cfg: Dict[str, Any]) -> None:
        """Validate the loaded configuration dict and raise on invalid settings.

        This is intentionally strict and fails early, before downloading files or
        starting subprocess work.
        """
        required_common = ("verapdf_path", "output_dir", "max_processes", "scope")
        missing = [k for k in required_common if k not in cfg]
        if missing:
            raise ValueError("Missing config keys: %s" % ", ".join(missing))

        source = str(cfg.get("source", "local")).lower()
        if source not in ("local", "box"):
            raise ValueError('source must be "local" or "box".')

        if source == "local":
            if "root_folder" not in cfg:
                raise ValueError("Missing config key: root_folder (required when source is local).")
            root = Path(str(cfg["root_folder"]))
            if not root.is_dir():
                raise FileNotFoundError("root_folder is not a directory: %s" % root)
        else:
            box = cfg.get("box")
            if not isinstance(box, dict):
                raise ValueError("When source is box, config must include a 'box' mapping.")
            if not str(box.get("developer_token") or "").strip():
                raise ValueError(
                    "When source is box, set box.developer_token to your Developer Token from "
                    "the Box Developer Console (Configuration → Developer Token)."
                )
            if not str(box.get("root_folder_id") or "").strip():
                raise ValueError(
                    "When source is box, set box.root_folder_id to the Box folder ID (from the folder URL)."
                )

        # Resolved earlier in run(); still validate type.
        vp = Path(str(cfg["verapdf_path"]))
        if not vp.is_file():
            raise FileNotFoundError("verapdf_path is not a file: %s" % vp)

        mp = int(cfg["max_processes"])
        if mp < 1:
            raise ValueError("max_processes must be >= 1.")

        scope = cfg["scope"]
        if not isinstance(scope, dict):
            raise ValueError("scope must be a mapping with mode (and students when needed).")
        mode = str(scope.get("mode", "all")).strip().lower()
        if mode not in ("all", "students"):
            raise ValueError('scope.mode must be "all" or "students".')
        if mode == "students":
            students = scope.get("students")
            if not students or not isinstance(students, list):
                raise ValueError('When scope.mode is "students", scope.students must be a non-empty list.')
            if not any(str(s).strip() for s in students):
                raise ValueError(
                    'When scope.mode is "students", scope.students must include at least one non-blank name.'
                )

        # output_dir may be created later

    def run(self) -> Path:
        """Run the pipeline and write the Excel report.

        Returns:
            Path to the generated ``accessibility_audit_*.xlsx`` workbook.
        """
        cfg = self.load_config()
        merge_scope_students_from_root(cfg)
        cfg["verapdf_path"] = str(resolve_verapdf_path(cfg.get("verapdf_path")))
        self.validate_config(cfg)

        out_dir = Path(str(cfg["output_dir"]))
        out_dir.mkdir(parents=True, exist_ok=True)
        stderr_log = str(out_dir / "verapdf_stderr.log")

        source = str(cfg.get("source", "local")).lower()
        if source == "local":
            records = LocalFileScanner(str(cfg["root_folder"]), cfg.get("scope")).scan()
            root_for_report = str(Path(cfg["root_folder"]).resolve())
        else:
            from box_auth import create_box_client
            from box_folder_scanner import BoxFolderScanner

            box = cfg.get("box")
            if not isinstance(box, dict):
                raise TypeError("box configuration must be a mapping.")
            staging = Path(str(box.get("staging_dir") or "box_staging").strip())
            if not staging.is_absolute():
                staging = (Path.cwd() / staging).resolve()
            else:
                staging = staging.resolve()
            client = create_box_client(cfg)
            records = BoxFolderScanner(
                client,
                str(box["root_folder_id"]).strip(),
                staging,
                cfg.get("scope"),
                clear_staging=bool(box.get("clear_staging_before_run", True)),
            ).scan()
            root_for_report = str(staging)

        timeout = cfg.get("timeout_seconds")
        if timeout is not None:
            timeout = float(timeout)

        runner = VeraPDFRunner(
            verapdf_path=str(cfg["verapdf_path"]),
            max_processes=int(cfg["max_processes"]),
            disable_error_messages=bool(cfg.get("disable_error_messages", False)),
            timeout_seconds=timeout,
            stderr_log_path=stderr_log,
        )

        # Convert records to the path list expected by the veraPDF CLI runner.
        paths = [r.path for r in records]
        xml_text = runner.run_batch(paths)
        reports: List[ValidationReport] = ValidationReport.parse_batch(
            xml_text, records, root_for_report
        )

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_xlsx = out_dir / f"accessibility_audit_{stamp}.xlsx"
        ReportBuilder().build_and_save(reports, out_xlsx)
        return out_xlsx


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point. Returns process exit code (0 on success, 1 on error)."""
    argv = list(argv if argv is not None else sys.argv[1:])
    default_config = Path(__file__).resolve().parent / "config.yaml"
    config_path = default_config
    if argv:
        if argv[0] in ("-h", "--help"):
            print("Usage: python audit_pipeline.py [config.yaml]")
            return 0
        config_path = Path(argv[0])

    try:
        out = AuditPipeline(str(config_path)).run()
    except Exception as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return 1

    print("Wrote report: %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
