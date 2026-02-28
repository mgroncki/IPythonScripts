"""
impact_summarizer.py — Step 4: parse ORE stresstest.csv output, compute P&L
impacts, and generate a human-readable narrative via LLM.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pandas as pd
from openai import OpenAI

import config

# ── CSV parsing ───────────────────────────────────────────────────────────────

def _read_stresstest_csv(csv_path: Path, scenario_id: str) -> pd.DataFrame:
    """
    Load stresstest.csv and return rows matching *scenario_id*.

    The file has a header line that starts with ``#TradeId`` — pandas handles
    the ``#`` by treating it as part of the first column name, so we strip it.
    """
    with csv_path.open() as f:
        content = f.read()

    # Remove leading # from the header line
    content = content.replace("#TradeId", "TradeId", 1)

    df = pd.read_csv(io.StringIO(content))
    df.columns = [c.strip() for c in df.columns]

    # Filter to this scenario
    mask = df["ScenarioLabel"].str.strip() == scenario_id
    filtered = df[mask].copy()

    if filtered.empty:
        raise ValueError(
            f"No results found for scenario '{scenario_id}' in {csv_path}.\n"
            f"Available scenarios: {df['ScenarioLabel'].unique().tolist()}"
        )

    filtered["PnL"] = filtered["Scenario NPV"] - filtered["Base NPV"]
    return filtered


# ── Analysis helpers ──────────────────────────────────────────────────────────

def _compute_summary(df: pd.DataFrame) -> dict[str, Any]:
    """Return a dict with totals and per-trade data."""
    total_base = df["Base NPV"].sum()
    total_stressed = df["Scenario NPV"].sum()
    total_pnl = total_stressed - total_base

    rows = df.sort_values("PnL").to_dict(orient="records")

    return {
        "total_base_npv": total_base,
        "total_stressed_npv": total_stressed,
        "total_pnl": total_pnl,
        "trades": rows,
        "top_losers": sorted(rows, key=lambda r: r["PnL"])[:3],
        "top_gainers": sorted(rows, key=lambda r: r["PnL"], reverse=True)[:3],
    }


# ── Markdown table ────────────────────────────────────────────────────────────

def _format_table(summary: dict[str, Any]) -> str:
    """Build a Markdown results table."""
    lines = [
        "| Trade | Base NPV | Stressed NPV | P&L Impact |",
        "|-------|----------|--------------|------------|",
    ]
    for row in summary["trades"]:
        pnl_str = f"{row['PnL']:+,.0f}"
        lines.append(
            f"| {row['TradeId']} "
            f"| {row['Base NPV']:,.0f} "
            f"| {row['Scenario NPV']:,.0f} "
            f"| {pnl_str} |"
        )
    lines.append(
        f"| **TOTAL** "
        f"| **{summary['total_base_npv']:,.0f}** "
        f"| **{summary['total_stressed_npv']:,.0f}** "
        f"| **{summary['total_pnl']:+,.0f}** |"
    )
    return "\n".join(lines)


# ── LLM narrative ─────────────────────────────────────────────────────────────

_NARRATIVE_SYSTEM = """\
You are a senior risk analyst writing a concise executive summary of a
portfolio stress test. Keep the summary to 3-4 paragraphs. Use plain prose —
no bullet points. Be specific about the numbers provided.
"""

def _llm_narrative(
    scenario_description: str,
    shifts: dict[str, Any],
    summary: dict[str, Any],
) -> str:
    """Call the LLM to produce a narrative paragraph about the results."""
    if not config.OPENAI_API_KEY:
        return (
            "(LLM narrative unavailable — OPENAI_API_KEY not set)\n\n"
            f"Total P&L impact: {summary['total_pnl']:+,.0f} EUR"
        )

    client = OpenAI(api_key=config.OPENAI_API_KEY)

    # ── Build a shifts summary from the generic schema ──
    shift_lines: list[str] = []

    # FX
    for pair, v in shifts.get("fx", {}).items():
        shift_lines.append(f"  FX {pair}: {v:+.4f} (absolute)")

    # Equity
    for key, v in shifts.get("equity", {}).items():
        shift_lines.append(f"  Equity {key}: {v:+.1%}")

    # Rates
    for ccy, tenors in shifts.get("rates", {}).items():
        parts = " / ".join(f"{t} {val*1e4:+.0f}bp" for t, val in tenors.items())
        shift_lines.append(f"  Rates {ccy}: {parts}")

    # Credit
    for key, tenors in shifts.get("credit", {}).items():
        parts = " / ".join(f"{t} {val*1e4:+.0f}bp" for t, val in tenors.items())
        shift_lines.append(f"  Credit {key}: {parts}")

    shifts_text = "\n".join(shift_lines) if shift_lines else "  (none)"

    prompt = f"""\
Scenario description: {scenario_description}

Applied market shifts:
{shifts_text}

Portfolio results (all in EUR, base currency):
  Base portfolio NPV:     {summary['total_base_npv']:,.0f}
  Stressed portfolio NPV: {summary['total_stressed_npv']:,.0f}
  Total P&L impact:       {summary['total_pnl']:+,.0f}

Trade-level impacts (sorted by P&L):
""" + "\n".join(
        f"  {r['TradeId']:30s} Base: {r['Base NPV']:>14,.0f}  "
        f"Stressed: {r['Scenario NPV']:>14,.0f}  P&L: {r['PnL']:>+14,.0f}"
        for r in summary["trades"]
    ) + f"""

Top losers:  {', '.join(r['TradeId'] for r in summary['top_losers'])}
Top gainers: {', '.join(r['TradeId'] for r in summary['top_gainers'])}

Write an executive summary explaining which asset classes drove the result,
which trades were most affected, and what the overall risk interpretation is.
"""

    resp = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _NARRATIVE_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
    )
    return resp.choices[0].message.content or ""


# ── Main entry point ──────────────────────────────────────────────────────────

def summarize(
    csv_path: Path,
    scenario_description: str,
    shifts: dict[str, Any],
    scenario_id: str = "agent_scenario",
) -> str:
    """
    Parse *csv_path*, compute impacts, and return a Markdown report string.

    Parameters
    ----------
    csv_path             : path to stresstest.csv produced by ORE
    scenario_description : original user text (used for narrative prompt)
    shifts               : the shifts dict from scenario_analyzer.analyze()
    scenario_id          : the StressTest id used when building the XML

    Returns
    -------
    Markdown-formatted report string.
    """
    df = _read_stresstest_csv(csv_path, scenario_id)
    summary = _compute_summary(df)
    table = _format_table(summary)
    narrative = _llm_narrative(scenario_description, shifts, summary)

    header = (
        "═" * 60 + "\n"
        "  Portfolio Stress Test Impact Report\n"
        "═" * 60
    )

    pnl_sign = "+" if summary["total_pnl"] >= 0 else ""
    pnl_label = f"TOTAL P&L: {pnl_sign}{summary['total_pnl']:,.0f} EUR"
    direction = "GAIN" if summary["total_pnl"] >= 0 else "LOSS"

    report = (
        f"{header}\n\n"
        f"**{pnl_label}  [{direction}]**\n\n"
        f"{table}\n\n"
        "---\n\n"
        "**Narrative Summary**\n\n"
        f"{narrative}\n"
    )
    return report
