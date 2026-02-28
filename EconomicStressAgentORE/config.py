"""
config.py — central configuration for the Economic Scenario Stress Test Agent.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"                # raw data files (e.g. historical scenarios)
ORE_WORKSPACE = BASE_DIR / "oredata"          # workspace that contains ore.xml
ORE_INPUT_DIR = ORE_WORKSPACE / "Input"
ORE_OUTPUT_DIR = ORE_WORKSPACE / "Output"

# Generated files written by the agent
AGENT_STRESS_XML = ORE_INPUT_DIR / "agent_stress.xml"
AGENT_ORE_XML = ORE_WORKSPACE / "ore_agent.xml"

# ── LLM ───────────────────────────────────────────────────────────────────────
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5.2")
OPENAI_TEMPERATURE: float = float(os.getenv("OPENAI_TEMPERATURE", "0.2"))

# ── Sector-mapping CSV (maps equity/credit names → sectors) ───────────────────
SECTOR_MAPPING_CSV: Path = BASE_DIR / "sector_mapping.csv"

# ── Standard tenor grids (used when generating simulation.xml & stresstest) ───
STANDARD_RATE_TENORS: list[str] = [
    "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "30Y",
]

STANDARD_CREDIT_TENORS: list[str] = [
    "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y",
]

STANDARD_INFLATION_TENORS: list[str] = [
    "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "30Y",
]

STANDARD_EQUITY_DIV_TENORS: list[str] = [
    "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y",
]
