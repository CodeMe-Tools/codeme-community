"""Diagnostics contract implementation for codeme-verify."""

from dataclasses import dataclass
import json
import uuid
from typing import Any, Dict, List, Optional


@dataclass
class VerifyDiagnostic:
    code: str
    file: str
    line: int
    column: int
    message: str
    remediation: str
    severity: str = "error"
    rule_id: Optional[str] = None

    def format_text(self) -> str:
        loc = f"{self.file}:{self.line}:{self.column}" if self.line > 0 else self.file
        return f"[{self.code}] {loc}: {self.message}\n  Remediation: {self.remediation}"

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "code": self.code,
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "severity": self.severity,
            "message": self.message,
            "remediation": self.remediation,
        }
        if self.rule_id:
            data["rule_id"] = self.rule_id
        return data


def format_diagnostics_json(
    run_id: str,
    status: str,
    exit_code: int,
    diagnostics: List[VerifyDiagnostic],
    duration_ms: float = 0.0,
    raw_output_bytes: int = 0,
    suppressed_bytes: int = 0,
) -> str:
    """Format diagnostics adhering to schemas/diagnostic-contract.v1.json."""
    diag_dicts = [d.to_dict() for d in diagnostics]
    diag_bytes = len(json.dumps(diag_dicts).encode("utf-8"))
    payload = {
        "run_id": run_id or str(uuid.uuid4()),
        "status": status,
        "exit_code": exit_code,
        "duration_ms": round(duration_ms, 2),
        "diagnostics": diag_dicts,
        "token_metrics": {
            "raw_output_bytes": raw_output_bytes,
            "diagnostic_bytes": diag_bytes,
            "suppressed_bytes": suppressed_bytes,
            "estimated_tokens_saved": max(0, (suppressed_bytes - diag_bytes) // 4),
        },
    }
    return json.dumps(payload, indent=2)
