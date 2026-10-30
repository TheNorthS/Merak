from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from server.services.experiment_placeholders import (
    _paired_t_two_sided_p,
    _publication_component_label,
    _publication_metric_label,
    _publication_outcome_label,
    experiment_placeholder_service,
)
from server.services.paper_artifacts import paper_artifact_builder
from server.services.scientific_assets import scientific_asset_service
from server.services.simulation_policy import (
    SIMULATION_MANIFEST_SCHEMA,
    SIMULATION_PLOT_FAMILIES,
    SIMULATION_RENDERER_VERSION,
    simulation_manifest_contract_issues,
)
from server.workflows.engine import WorkflowEngine, WorkflowRun


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
