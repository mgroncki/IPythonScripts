"""
scenario_analyzer.py — Step 1: map a free-text economic scenario to concrete
market shifts using an LLM + an in-process historical knowledge base.
"""

from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

import config
from historical_scenarios import ScenarioKnowledgeBase

# ── System prompt ─────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are a quantitative risk analyst specialising in macro stress testing.

You are given a knowledge base of historical economic crises and their
approximate market impacts, and a user-described economic scenario.

Your task is to:
1. Identify which historical episodes best match the described scenario
   (pick 1-3 episodes).
2. Derive a *weighted average* of the market shifts from those episodes that
   best represents the described scenario. You may scale the shifts up or down
   to reflect the described severity.
3. Return a JSON object (and nothing else) with this exact schema:

{
  "matched_scenarios": ["<episode name>", ...],
  "reasoning": "<short explanation>",
  "shifts": {
    "rates": {
      "<CCY>": { "<tenor>": <float>, ... }
    },
    "fx": { "<PAIR>": <float> },
    "equity": {
      "<CCY_or_sector>": <float>
    },
    "credit": {
      "<CCY_or_sector>": { "<tenor>": <float>, ... }
    }
  }
}

Keys:
- rates: keyed by ISO currency (EUR, USD, …). Values are absolute changes
  in swap/yield rates in decimal (e.g. -0.015 = -150 bps, +0.010 = +100 bps).
  Tenors: 1Y, 2Y, 3Y, 5Y, 10Y, 30Y (at minimum include 1Y, 2Y, 5Y, 10Y, 30Y).
- fx: keyed by pair (e.g. "EURUSD"). Value is the absolute change in the spot
  rate (e.g. -0.08 means EUR falls 8 big figures vs USD).
- equity: keyed by Currency (e.g. "EUR", "USD") or sector override
  (e.g. "Tech", "Index"). Values are relative (fractional) changes
  (e.g. -0.25 = -25 %). Always include at least the currency-level keys.
- credit: keyed by Currency or sector (e.g. "EUR", "USD",
  "SeniorUnsecured", "Sovereign"). Values are dicts of tenor → absolute
  shift to hazard/CDS spread (positive = widening, e.g. 0.02 = +200 bps).
  Tenors: 1Y, 2Y, 3Y, 5Y, 10Y.

Return ONLY the JSON object — no markdown fences, no extra text.
"""


def _build_user_message(
    scenario_description: str,
    knowledge_base: ScenarioKnowledgeBase,
) -> str:
    """Combine the historical knowledge base with the user's scenario."""
    kb = knowledge_base.get_scenarios_text()
    return (
        f"## Historical Scenarios Knowledge Base\n\n{kb}\n\n"
        f"## User-Described Scenario\n\n{scenario_description}\n\n"
        "Analyse the described scenario and return the JSON object as instructed."
    )


def analyze(
    scenario_description: str,
    knowledge_base: ScenarioKnowledgeBase,
) -> dict[str, Any]:
    """
    Analyse *scenario_description* and return a structured dict of market shifts.

    Returns
    -------
    dict with keys:
        matched_scenarios : list[str]
        reasoning         : str
        shifts            : dict  (fx, equity, rates_eur, rates_usd)
    """
    if not config.OPENAI_API_KEY:
        raise EnvironmentError(
            "OPENAI_API_KEY is not set. Please add it to your .env file."
        )

    client = OpenAI(api_key=config.OPENAI_API_KEY)

    response = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_message(scenario_description, knowledge_base)},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content or "{}"

    # Strip accidental markdown fences if the model includes them
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"```\s*$", "", raw.strip())

    result: dict[str, Any] = json.loads(raw)
    _validate(result)
    return result


def _validate(result: dict[str, Any]) -> None:
    """Raise ValueError if the returned JSON is missing required keys."""
    required_top = {"matched_scenarios", "reasoning", "shifts"}
    missing = required_top - result.keys()
    if missing:
        raise ValueError(f"LLM response missing keys: {missing}")

    shifts = result["shifts"]
    required_shifts = {"rates", "fx", "equity", "credit"}
    missing_shifts = required_shifts - shifts.keys()
    if missing_shifts:
        raise ValueError(f"shifts missing sub-keys: {missing_shifts}")


def format_shifts(result: dict[str, Any]) -> str:
    """Return a human-readable string of the proposed shifts."""
    s = result["shifts"]
    lines = [
        "Matched scenarios:",
        *[f"  • {name}" for name in result["matched_scenarios"]],
        "",
        f"Reasoning: {result['reasoning']}",
        "",
        "Proposed market shifts:",
    ]

    # FX
    for pair, v in s.get("fx", {}).items():
        lines.append(f"  FX {pair}: {v:+.4f}")

    # Equity
    for key, v in s.get("equity", {}).items():
        lines.append(f"  Equity {key}: {v:+.1%}")

    # Rates
    for ccy, tenors in s.get("rates", {}).items():
        parts = "  ".join(f"{t} {v*10000:+.0f}bp" for t, v in tenors.items())
        lines.append(f"  Rates {ccy}: {parts}")

    # Credit
    for key, tenors in s.get("credit", {}).items():
        parts = "  ".join(f"{t} {v*10000:+.0f}bp" for t, v in tenors.items())
        lines.append(f"  Credit {key}: {parts}")

    return "\n".join(lines)
