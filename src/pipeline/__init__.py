"""
Demand Spike Detector - Data Pipeline
=====================================
Extensible plugin-based pipeline for collecting external factors
that affect demand patterns.
"""

from .base import BaseFactorPlugin, FactorRecord, FactorType
from .registry import PluginRegistry
from .orchestrator import PipelineOrchestrator

__all__ = [
    "BaseFactorPlugin",
    "FactorRecord",
    "FactorType",
    "PluginRegistry",
    "PipelineOrchestrator",
]
