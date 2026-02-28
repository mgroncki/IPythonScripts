"""
ore_runner.py — Step 3: execute ORE with the agent-generated stress test config
and return the path to the output stresstest.csv.

Uses the ORE Python bindings (``from ORE import *``).
ORE is logically "run from" the OREDir workspace directory so
that relative ``inputPath`` / ``outputPath`` in ore.xml resolve correctly.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import config


# ── Public API ────────────────────────────────────────────────────────────────

def run(
    ore_xml: Path | str | None = None,
    workspace: Path | str | None = None,
) -> Path:
    """
    Run ORE and return the path to the output stresstest.csv.

    Parameters
    ----------
    ore_xml   : path to the ORE main config file.
                Defaults to ``config.AGENT_ORE_XML``.
    workspace : directory from which ORE should be launched.
                Defaults to ``config.ORE_WORKSPACE``.

    Returns
    -------
    Path to ``Output/stresstest.csv`` inside the workspace.
    """
    if ore_xml is None:
        ore_xml = config.AGENT_ORE_XML
    if workspace is None:
        workspace = config.ORE_WORKSPACE

    ore_xml = Path(ore_xml)
    workspace = Path(workspace)

    if not ore_xml.exists():
        raise FileNotFoundError(f"ORE config not found: {ore_xml}")
    if not workspace.exists():
        raise FileNotFoundError(f"ORE workspace not found: {workspace}")

    # Path passed to ORE should be relative to the workspace (since ORE resolves
    # Input/Output paths relative to its own working directory).
    try:
        ore_xml_rel = ore_xml.relative_to(workspace)
    except ValueError:
        ore_xml_rel = ore_xml  # use absolute if not inside workspace

    # Clean the Output directory so stale results never mask a real failure.
    output_dir = workspace / "Output"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    _run_via_python_api(ore_xml_rel, workspace)

    stdout_csv = workspace / "Output" / "stresstest.csv"
    if not stdout_csv.exists():
        raise RuntimeError(
            f"ORE run did not produce stresstest.csv at {stdout_csv}.\n"
            "Check the ORE log at: " + str(workspace / "Output" / "log.txt")
        )
    return stdout_csv


# ── Execution back-end ─────────────────────────────────────────────────────────

def _run_via_python_api(ore_xml_rel: Path, workspace: Path) -> None:
    """Execute ORE using the Python bindings (OREApp)."""
    from ORE import OREApp, Parameters  # type: ignore[import]
    print(f"Running ORE with config: {ore_xml_rel} from workspace: {workspace}")
    orig_cwd = Path.cwd()
    try:
        os.chdir(workspace)
        params = Parameters()
        params.fromFile(str(ore_xml_rel))
        ore = OREApp(params, True)
        ore.run()
    finally:
        os.chdir(orig_cwd)
