"""
stresstest_builder.py — Step 2: convert structured market shifts into an
ORE-compatible par stress test XML file.

This version is **market-driven**: it accepts a ``MarketStructure`` (from
``todaysmarket_analyzer.parse()``) and a sector mapping so that every curve
present in todaysmarket.xml is automatically stressed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.dom import minidom
from xml.etree import ElementTree as ET

import config
import ORE  

from todaysmarket_analyzer import (
    CurveInfo,
    MarketStructure,
    SectorEntry,
    load_sector_mapping,
    resolve_credit_shifts,
    resolve_equity_shift,
)

# ── Tenor helpers ─────────────────────────────────────────────────────────────

def _tenor_to_year_fraction(tenor: str, today, day_counter) -> float:
    """Convert an ORE tenor string to a year-fraction relative to *today*."""
    
    return day_counter.yearFraction(today, today + ORE.Period(tenor.strip()))


def interpolate_shift(
    tenors: list[str], scenario_shifts: dict[str, float]
) -> list[float]:
    """
    Linear interpolation with flat extrapolation of scenario key-tenor
    shifts onto an arbitrary ORE tenor grid, using ORE's own date/period
    logic and ``LinearInterpolation``.
    """
    if not scenario_shifts:
        return [0.0] * len(tenors)

    today = ORE.Settings.instance().evaluationDate
    dc = ORE.Actual365Fixed()

    # Build sorted anchor arrays from scenario shifts
    anchors = sorted(
        (_tenor_to_year_fraction(t, today, dc), v)
        for t, v in scenario_shifts.items()
    )
    xs = [a[0] for a in anchors]
    ys = [a[1] for a in anchors]

    interp = ORE.LinearInterpolation(xs, ys)

    def _lookup(t_yf: float) -> float:
        if t_yf <= xs[0]:
            return ys[0]
        if t_yf >= xs[-1]:
            return ys[-1]
        return interp(t_yf)

    return [
        _lookup(_tenor_to_year_fraction(t, today, dc))
        for t in tenors
    ]


# ── XML helpers ───────────────────────────────────────────────────────────────

def _shifts_str(values: list[float]) -> str:
    """Format a list of shift values as a comma-separated string."""
    return ", ".join(f"{v:.6f}" for v in values)


def _add_curve_element(
    parent: ET.Element,
    tag: str,
    attr: dict[str, str],
    tenors: list[str],
    shifts: list[float],
) -> None:
    """Append a <DiscountCurve> or <IndexCurve> element with shifts."""
    el = ET.SubElement(parent, tag, attr)
    ET.SubElement(el, "ShiftType").text = "Absolute"
    ET.SubElement(el, "Shifts").text = _shifts_str(shifts)
    ET.SubElement(el, "ShiftTenors").text = ", ".join(tenors)


def _prettify(element: ET.Element) -> str:
    """Return a pretty-printed XML string (no blank lines)."""
    rough = ET.tostring(element, encoding="unicode")
    reparsed = minidom.parseString(rough)
    xml = reparsed.toprettyxml(indent="  ", encoding=None)
    # minidom inserts blank lines when the source already has whitespace nodes
    return "\n".join(line for line in xml.splitlines() if line.strip())


# ── Main builder ──────────────────────────────────────────────────────────────

def _resolve_rate_shifts(
    ccy: str, shifts: dict[str, Any]
) -> dict[str, float]:
    """Return the rate tenor-shift dict for a currency (empty if missing)."""
    rates: dict = shifts.get("rates", {})
    return rates.get(ccy, {})


def build(
    shifts: dict[str, Any],
    market: MarketStructure | None = None,
    sector_map: dict[tuple[str, str], SectorEntry] | None = None,
    output_path: Path | None = None,
    scenario_id: str = "agent_scenario",
    scenario_label: str | None = None,
) -> Path:
    """
    Build the ORE stress test XML from *shifts* (generic schema) and the
    discovered *market* structure.

    Parameters
    ----------
    shifts       : generic schema ``{rates, fx, equity, credit}``
    market       : MarketStructure — if None, parsed from todaysmarket.xml
    sector_map   : sector mapping — if None, loaded from config
    output_path  : where to write the XML
    scenario_id  : ``id`` attribute of the ``<StressTest>`` element
    scenario_label : optional human-readable label embedded as a comment
    """
    from todaysmarket_analyzer import parse as tm_parse  # local to avoid circular

    if market is None:
        market = tm_parse()
    if sector_map is None:
        sector_map = load_sector_mapping()
    if output_path is None:
        output_path = config.AGENT_STRESS_XML

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Root
    root = ET.Element("StressTesting")
    ET.SubElement(root, "UseSpreadedTermStructures").text = "true"

    st = ET.SubElement(root, "StressTest", {"id": scenario_id})
    if scenario_label:
        st.append(ET.Comment(f" {scenario_label} "))

    par = ET.SubElement(st, "ParShifts")
    ET.SubElement(par, "IRCurves").text = "false"
    ET.SubElement(par, "SurvivalProbability").text = "false"
    ET.SubElement(par, "CapFloorVolatilities").text = "false"

    # ── Discount curves ────────────────────────────────────────────────
    disc_el = ET.SubElement(st, "DiscountCurves")
    for curve in market.discount_curves:
        rate_shifts = _resolve_rate_shifts(curve.currency, shifts)
        if not rate_shifts:
            continue
        tenors = config.STANDARD_RATE_TENORS
        interp = interpolate_shift(tenors, rate_shifts)
        _add_curve_element(disc_el, "DiscountCurve",
                           {"ccy": curve.currency}, tenors, interp)

    # ── Index curves ───────────────────────────────────────────────────
    idx_el = ET.SubElement(st, "IndexCurves")
    for curve in market.index_curves:
        rate_shifts = _resolve_rate_shifts(curve.currency, shifts)
        if not rate_shifts:
            continue
        tenors = config.STANDARD_RATE_TENORS
        interp = interpolate_shift(tenors, rate_shifts)
        _add_curve_element(idx_el, "IndexCurve",
                           {"index": curve.name}, tenors, interp)

    # ── Yield curves ───────────────────────────────────────────────────
    yc_el = ET.SubElement(st, "YieldCurves")
    for curve in market.yield_curves:
        rate_shifts = _resolve_rate_shifts(curve.currency, shifts)
        if not rate_shifts:
            continue
        tenors = config.STANDARD_RATE_TENORS
        interp = interpolate_shift(tenors, rate_shifts)
        _add_curve_element(yc_el, "YieldCurve",
                           {"name": curve.name}, tenors, interp)

    # ── FX spots ───────────────────────────────────────────────────────
    fx_el = ET.SubElement(st, "FxSpots")
    fx_shifts: dict[str, float] = shifts.get("fx", {})
    for pair in market.fx_pairs:
        foreign = pair[:3]
        domestic = pair[3:]
        # Try both conventions
        raw_shift = fx_shifts.get(pair, fx_shifts.get(domestic + foreign, None))
        if raw_shift is None:
            continue
        # ORE uses inverted convention (USDEUR)
        ore_pair = domestic + foreign
        if pair == ore_pair:
            relative_shift = raw_shift
        else:
            # EURUSD scenario → USDEUR in ORE: negate
            relative_shift = -raw_shift
        spot_el = ET.SubElement(fx_el, "FxSpot", {"ccypair": ore_pair})
        ET.SubElement(spot_el, "ShiftType").text = "Relative"
        ET.SubElement(spot_el, "ShiftSize").text = f"{relative_shift:.6f}"

    # ── FxVolatilities (empty) ────────────────────────────────────────
    ET.SubElement(st, "FxVolatilities")

    # ── SwaptionVolatilities (empty) ──────────────────────────────────
    ET.SubElement(st, "SwaptionVolatilities")

    # ── CapFloorVolatilities (empty) ──────────────────────────────────
    ET.SubElement(st, "CapFloorVolatilities")

    # ── Equity spots ─────────────────────────────────────────────────
    eq_el = ET.SubElement(st, "EquitySpots")
    for curve in market.equity_curves:
        rel_shift = resolve_equity_shift(curve, shifts, sector_map)
        if rel_shift == 0.0:
            continue
        eq_spot = ET.SubElement(eq_el, "EquitySpot", {"equity": curve.name})
        ET.SubElement(eq_spot, "ShiftType").text = "Relative"
        ET.SubElement(eq_spot, "ShiftSize").text = f"{rel_shift:.6f}"

    # ── EquityVolatilities (empty) ────────────────────────────────────
    ET.SubElement(st, "EquityVolatilities")

    # ── SecuritySpreads, RecoveryRates (empty) ────────────────────────
    ET.SubElement(st, "SecuritySpreads")
    ET.SubElement(st, "RecoveryRates")

    # ── Survival probabilities ────────────────────────────────────────
    surv_el = ET.SubElement(st, "SurvivalProbabilities")
    for curve in market.default_curves:
        credit_tenor_shifts = resolve_credit_shifts(curve, shifts, sector_map)
        if not credit_tenor_shifts:
            continue
        tenors = config.STANDARD_CREDIT_TENORS
        interp = interpolate_shift(tenors, credit_tenor_shifts)
        sp = ET.SubElement(surv_el, "SurvivalProbability", {"name": curve.name})
        ET.SubElement(sp, "ShiftType").text = "Absolute"
        ET.SubElement(sp, "Shifts").text = _shifts_str(interp)
        ET.SubElement(sp, "ShiftTenors").text = ", ".join(tenors)

    # ── Serialise ─────────────────────────────────────────────────────
    xml_str = _prettify(root)
    lines = xml_str.splitlines()
    if lines and lines[0].startswith("<?xml"):
        lines = lines[1:]
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def build_ore_config(
    base_ore_xml: Path | None = None,
    output_ore_xml: Path | None = None,
    stress_config_file: str = "agent_stress.xml",
) -> Path:
    """
    Write a minimal ore_agent.xml that activates only the stress analytic and
    points to the agent-generated stress test configuration.

    Parameters
    ----------
    base_ore_xml        : source ore.xml to base settings on
                          (defaults to config.ORE_WORKSPACE / "ore.xml")
    output_ore_xml      : where to write the agent ore config
                          (defaults to config.AGENT_ORE_XML)
    stress_config_file  : filename (relative to Input/) of the stress XML

    Returns
    -------
    Path to the written file.
    """
    if base_ore_xml is None:
        base_ore_xml = config.ORE_WORKSPACE / "ore.xml"
    if output_ore_xml is None:
        output_ore_xml = config.AGENT_ORE_XML

    base_ore_xml = Path(base_ore_xml)
    output_ore_xml = Path(output_ore_xml)

    tree = ET.parse(base_ore_xml)
    root = tree.getroot()

    # Strip whitespace-only text/tail so _prettify produces clean output
    for el in root.iter():
        if el.text and not el.text.strip():
            el.text = None
        if el.tail and not el.tail.strip():
            el.tail = None

    # Disable every analytic except stress; update stress config file
    analytics = root.find("Analytics")
    if analytics is not None:
        for analytic in analytics.findall("Analytic"):
            atype = analytic.get("type", "")
            if atype == "stress":
                for param in analytic.findall("Parameter"):
                    if param.get("name") == "stressConfigFile":
                        param.text = stress_config_file
                    if param.get("name") == "active":
                        param.text = "Y"
            else:
                for param in analytic.findall("Parameter"):
                    if param.get("name") == "active":
                        param.text = "N"

    xml_str = _prettify(root)
    lines = xml_str.splitlines()
    if lines and lines[0].startswith("<?xml"):
        lines[0] = '<?xml version="1.0"?>'
    output_ore_xml.write_text("\n".join(lines), encoding="utf-8")

    return output_ore_xml
