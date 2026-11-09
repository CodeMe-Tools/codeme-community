"""Codeme Verify package: Multi-ecosystem build & test verification and repair."""

from codeme.verify.diagnostics import VerifyDiagnostic
from codeme.verify.discovery import DiscoveredProject, ProjectDiscovery
from codeme.verify.repair import MechanicalRepair
from codeme.verify.runner import TestRunner

__all__ = [
    "VerifyDiagnostic",
    "DiscoveredProject",
    "ProjectDiscovery",
    "MechanicalRepair",
    "TestRunner",
]
