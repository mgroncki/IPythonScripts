"""
todaysmarket_analyzer.py — Parse todaysmarket.xml to extract all market
entities (curves, FX pairs, equities, credit names, inflation indices).

Returns a MarketStructure dataclass consumed by the stress test builder
and can generate a matching simulation.xml.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from xml.dom import minidom
from xml.etree import ElementTree as ET

import config


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class CurveInfo:
    """A single market curve / entity extracted from todaysmarket.xml."""
    name: str           # e.g. "EUR-ESTER", "Underlying1", "RIC:.SPX"
    currency: str       # e.g. "EUR", "USD"
    curve_type: str     # "discount", "index", "yield", "default", "equity", "inflation"
    spec: str           # full ORE spec, e.g. "Yield/EUR/EUR-ESTER"


@dataclass
class MarketStructure:
    """Complete market topology derived from todaysmarket.xml."""
    base_currency: str = "EUR"
    discount_curves: list[CurveInfo] = field(default_factory=list)
    index_curves: list[CurveInfo] = field(default_factory=list)
    yield_curves: list[CurveInfo] = field(default_factory=list)
    default_curves: list[CurveInfo] = field(default_factory=list)
    equity_curves: list[CurveInfo] = field(default_factory=list)
    fx_pairs: list[str] = field(default_factory=list)
    inflation_indices: list[CurveInfo] = field(default_factory=list)
    capfloor_vols: list[CurveInfo] = field(default_factory=list)

    @property
    def currencies(self) -> set[str]:
        """Union of all currencies found across every curve."""
        ccys: set[str] = set()
        for curves in (self.discount_curves, self.index_curves,
                       self.yield_curves, self.default_curves,
                       self.equity_curves, self.inflation_indices):
            for c in curves:
                ccys.add(c.currency)
        # Also extract from FX pairs (first 3 and last 3 chars)
        for pair in self.fx_pairs:
            ccys.add(pair[:3])
            ccys.add(pair[3:])
        return ccys


# ── Sector mapping ────────────────────────────────────────────────────────────

@dataclass
class SectorEntry:
    entity_type: str   # "equity" | "credit"
    name: str          # ORE entity name
    currency: str      # optional override (empty → auto-detect)
    sector: str        # e.g. "Tech", "SeniorUnsecured"


def load_sector_mapping(csv_path: Path | None = None) -> dict[tuple[str, str], SectorEntry]:
    """
    Load sector_mapping.csv and return a lookup dict keyed by (type, name).

    Parameters
    ----------
    csv_path : path to CSV file; defaults to config.SECTOR_MAPPING_CSV

    Returns
    -------
    dict mapping (entity_type, entity_name) → SectorEntry
    """
    if csv_path is None:
        csv_path = config.SECTOR_MAPPING_CSV
    csv_path = Path(csv_path)

    mapping: dict[tuple[str, str], SectorEntry] = {}
    if not csv_path.exists():
        return mapping

    with csv_path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            entry = SectorEntry(
                entity_type=row["type"].strip(),
                name=row["name"].strip(),
                currency=row.get("currency", "").strip(),
                sector=row["sector"].strip(),
            )
            mapping[(entry.entity_type, entry.name)] = entry
    return mapping


def resolve_equity_shift(
    curve: CurveInfo,
    shifts: dict,
    sector_map: dict[tuple[str, str], SectorEntry],
) -> float:
    """Resolve the equity shift for a given equity curve.

    Priority: sector override → currency default → 0.
    """
    equity_shifts: dict = shifts.get("equity", {})
    entry = sector_map.get(("equity", curve.name))
    if entry and entry.sector in equity_shifts:
        return equity_shifts[entry.sector]
    if curve.currency in equity_shifts:
        return equity_shifts[curve.currency]
    return 0.0


def resolve_credit_shifts(
    curve: CurveInfo,
    shifts: dict,
    sector_map: dict[tuple[str, str], SectorEntry],
) -> dict[str, float]:
    """Resolve the credit tenor shifts for a given default curve.

    Priority: sector override → currency default → empty dict.
    """
    credit_shifts: dict = shifts.get("credit", {})
    entry = sector_map.get(("credit", curve.name))
    if entry and entry.sector in credit_shifts:
        return credit_shifts[entry.sector]
    if curve.currency in credit_shifts:
        return credit_shifts[curve.currency]
    return {}


# ── todaysmarket.xml parser ───────────────────────────────────────────────────

def _ccy_from_spec(spec: str) -> str:
    """Extract currency from an ORE curve spec like 'Yield/EUR/EUR-ESTER'."""
    parts = spec.split("/")
    if len(parts) >= 2:
        return parts[1]
    return ""


def _ccy_from_index_name(name: str) -> str:
    """Extract currency from an index name like 'EUR-ESTER' or 'USD-SOFR'."""
    parts = name.split("-")
    if parts and len(parts[0]) == 3 and parts[0].isalpha():
        return parts[0].upper()
    return ""


def parse(todaysmarket_xml: Path | None = None) -> MarketStructure:
    """
    Parse todaysmarket.xml and return the full market structure.

    Parameters
    ----------
    todaysmarket_xml : path to todaysmarket.xml; defaults to
                       config.ORE_INPUT_DIR / "todaysmarket.xml"
    """
    if todaysmarket_xml is None:
        todaysmarket_xml = config.ORE_INPUT_DIR / "todaysmarket.xml"
    todaysmarket_xml = Path(todaysmarket_xml)

    tree = ET.parse(todaysmarket_xml)
    root = tree.getroot()

    ms = MarketStructure()

    # ── Discount curves ───────────────────────────────────────────────
    for dc_section in root.findall(".//DiscountingCurves[@id='default']"):
        for dc in dc_section.findall("DiscountingCurve"):
            ccy = dc.get("currency", "")
            spec = (dc.text or "").strip()
            name = spec.split("/")[-1] if spec else ccy
            ms.discount_curves.append(
                CurveInfo(name=name, currency=ccy, curve_type="discount", spec=spec)
            )

    # ── Index forwarding curves ───────────────────────────────────────
    for idx_section in root.findall(".//IndexForwardingCurves[@id='default']"):
        for idx in idx_section.findall("Index"):
            name = idx.get("name", "")
            spec = (idx.text or "").strip()
            ccy = _ccy_from_index_name(name) or _ccy_from_spec(spec)
            ms.index_curves.append(
                CurveInfo(name=name, currency=ccy, curve_type="index", spec=spec)
            )

    # ── Yield curves ──────────────────────────────────────────────────
    for yc_section in root.findall(".//YieldCurves[@id='default']"):
        for yc in yc_section.findall("YieldCurve"):
            name = yc.get("name", "")
            spec = (yc.text or "").strip()
            ccy = _ccy_from_spec(spec)
            ms.yield_curves.append(
                CurveInfo(name=name, currency=ccy, curve_type="yield", spec=spec)
            )

    # ── Default curves ────────────────────────────────────────────────
    for dc_section in root.findall(".//DefaultCurves[@id='default']"):
        for dc in dc_section.findall("DefaultCurve"):
            name = dc.get("name", "")
            spec = (dc.text or "").strip()
            ccy = _ccy_from_spec(spec)
            ms.default_curves.append(
                CurveInfo(name=name, currency=ccy, curve_type="default", spec=spec)
            )

    # ── Equity curves ─────────────────────────────────────────────────
    for eq_section in root.findall(".//EquityCurves[@id='default']"):
        for eq in eq_section.findall("EquityCurve"):
            name = eq.get("name", "")
            spec = (eq.text or "").strip()
            ccy = _ccy_from_spec(spec)
            ms.equity_curves.append(
                CurveInfo(name=name, currency=ccy, curve_type="equity", spec=spec)
            )

    # ── FX pairs ──────────────────────────────────────────────────────
    for fx_section in root.findall(".//FxSpots[@id='default']"):
        for fx in fx_section.findall("FxSpot"):
            pair = fx.get("pair", "")
            if pair:
                ms.fx_pairs.append(pair)

    # ── Inflation indices ─────────────────────────────────────────────
    for zi_section in root.findall(".//ZeroInflationIndexCurves[@id='default']"):
        for zi in zi_section.findall("ZeroInflationIndexCurve"):
            name = zi.get("name", "")
            spec = (zi.text or "").strip()
            # Inflation specs: Inflation/EUHICPXT/... → ccy heuristic from name prefix
            ccy = name[:2] + "R" if name[:2] in ("EU", "US", "GB") else ""
            if name.startswith("EU"):
                ccy = "EUR"
            elif name.startswith("US"):
                ccy = "USD"
            elif name.startswith("GB"):
                ccy = "GBP"
            else:
                ccy = _ccy_from_spec(spec)
            ms.inflation_indices.append(
                CurveInfo(name=name, currency=ccy, curve_type="inflation", spec=spec)
            )

    # ── CapFloor volatilities ─────────────────────────────────────────
    for cf_section in root.findall(".//CapFloorVolatilities[@id='default']"):
        for cf in cf_section.findall("CapFloorVolatility"):
            key = cf.get("key", "")
            spec = (cf.text or "").strip()
            ccy = _ccy_from_index_name(key) or _ccy_from_spec(spec)
            ms.capfloor_vols.append(
                CurveInfo(name=key, currency=ccy, curve_type="capfloor_vol", spec=spec)
            )

    # Derive base currency from first discount curve or default to EUR
    if ms.discount_curves:
        ms.base_currency = ms.discount_curves[0].currency
    else:
        ms.base_currency = "EUR"

    return ms


# ── Simulation XML generation ─────────────────────────────────────────────────

def _prettify(element: ET.Element) -> str:
    """Return a pretty-printed XML string (no XML declaration)."""
    rough = ET.tostring(element, encoding="unicode")
    reparsed = minidom.parseString(rough)
    pretty = reparsed.toprettyxml(indent="  ")
    # Remove the XML declaration added by minidom
    lines = pretty.splitlines()
    if lines and lines[0].startswith("<?xml"):
        lines = lines[1:]
    return "\n".join(lines)


def generate_simulation_xml(
    market: MarketStructure,
    output_path: Path | None = None,
) -> Path:
    """
    Generate a simulation.xml from the discovered MarketStructure.

    Uses standard tenor grids from config for each curve type.

    Parameters
    ----------
    market      : MarketStructure from parse()
    output_path : where to write; defaults to config.ORE_INPUT_DIR / "simulation.xml"
    """
    if output_path is None:
        output_path = config.ORE_INPUT_DIR / "simulation.xml"
    output_path = Path(output_path)

    root = ET.Element("Simulation")
    mkt = ET.SubElement(root, "Market")

    # ── BaseCurrency ──────────────────────────────────────────────────
    ET.SubElement(mkt, "BaseCurrency").text = market.base_currency

    # ── Currencies ────────────────────────────────────────────────────
    ccys_el = ET.SubElement(mkt, "Currencies")
    for ccy in sorted(market.currencies):
        ET.SubElement(ccys_el, "Currency").text = ccy

    # ── YieldCurves (global config) ───────────────────────────────────
    yc_el = ET.SubElement(mkt, "YieldCurves")
    cfg = ET.SubElement(yc_el, "Configuration", {"curve": ""})
    ET.SubElement(cfg, "Tenors").text = ", ".join(config.STANDARD_RATE_TENORS)
    ET.SubElement(cfg, "Interpolation").text = "LogLinear"
    ET.SubElement(cfg, "Extrapolation").text = "FlatZero"

    # ── FxRates ───────────────────────────────────────────────────────
    fx_el = ET.SubElement(mkt, "FxRates")
    pairs_el = ET.SubElement(fx_el, "CurrencyPairs")
    for pair in market.fx_pairs:
        # ORE simulation uses inverted convention (USDEUR instead of EURUSD)
        foreign = pair[:3]
        domestic = pair[3:]
        sim_pair = domestic + foreign  # e.g. EURUSD → USDEUR
        ET.SubElement(pairs_el, "CurrencyPair").text = sim_pair

    # ── Indices ───────────────────────────────────────────────────────
    indices_el = ET.SubElement(mkt, "Indices")
    for idx in market.index_curves:
        ET.SubElement(indices_el, "Index").text = idx.name

    # ── BenchmarkCurves (empty) ───────────────────────────────────────
    ET.SubElement(mkt, "BenchmarkCurves")

    # ── CapFloorVolatilities ──────────────────────────────────────────
    if market.capfloor_vols:
        cf_el = ET.SubElement(mkt, "CapFloorVolatilities")
        ET.SubElement(cf_el, "Simulate").text = "true"
        ET.SubElement(cf_el, "ReactionToTimeDecay").text = "ForwardVariance"
        keys_el = ET.SubElement(cf_el, "Keys")
        for cv in market.capfloor_vols:
            ET.SubElement(keys_el, "Key").text = cv.name
            ET.SubElement(cf_el, "Expiries", {"key": cv.name}).text = (
                "1Y, 2Y, 3Y, 4Y, 5Y, 6Y, 7Y, 8Y, 9Y, 10Y, 12Y, 15Y, 20Y, 25Y, 30Y"
            )
            ET.SubElement(cf_el, "Strikes", {"key": cv.name}).text = (
                "-0.015, -0.01, 0, 0.0005"
            )
        ET.SubElement(cf_el, "AdjustOptionletPillars").text = "true"
        ET.SubElement(cf_el, "UseCapAtm").text = "false"
        ET.SubElement(cf_el, "SmileDynamics", {"key": ""}).text = "StickyStrike"
        for cv in market.capfloor_vols:
            ET.SubElement(cf_el, "SmileDynamics", {"key": cv.name}).text = "StickyStrike"

    # ── DefaultCurves ─────────────────────────────────────────────────
    if market.default_curves:
        dc_el = ET.SubElement(mkt, "DefaultCurves")
        names_el = ET.SubElement(dc_el, "Names")
        for dc in market.default_curves:
            ET.SubElement(names_el, "Name").text = dc.name
        ET.SubElement(dc_el, "Tenors").text = ", ".join(config.STANDARD_CREDIT_TENORS)
        ET.SubElement(dc_el, "SimulateSurvivalProbabilities").text = "true"
        ET.SubElement(dc_el, "SimulateRecoveryRates").text = "false"
        cals = ET.SubElement(dc_el, "Calendars")
        ET.SubElement(cals, "Calendar", {"name": ""}).text = "TARGET"
        ET.SubElement(dc_el, "Extrapolation").text = "FlatZero"

    # ── ZeroInflationIndexCurves ──────────────────────────────────────
    if market.inflation_indices:
        zi_el = ET.SubElement(mkt, "ZeroInflationIndexCurves")
        names_el = ET.SubElement(zi_el, "Names")
        for zi in market.inflation_indices:
            ET.SubElement(names_el, "Name").text = zi.name
        ET.SubElement(zi_el, "Tenors").text = ", ".join(config.STANDARD_INFLATION_TENORS)

    # ── Equities ──────────────────────────────────────────────────────
    if market.equity_curves:
        eq_el = ET.SubElement(mkt, "Equities")
        ET.SubElement(eq_el, "SimulateDividendYield").text = "true"
        names_el = ET.SubElement(eq_el, "Names")
        for eq in market.equity_curves:
            ET.SubElement(names_el, "Name").text = eq.name
        ET.SubElement(eq_el, "DividendTenors").text = ", ".join(
            config.STANDARD_EQUITY_DIV_TENORS
        )

    # ── CreditStates (empty) ─────────────────────────────────────────
    cs = ET.SubElement(mkt, "CreditStates")
    ET.SubElement(cs, "NumberOfFactors").text = "0"
    acs = ET.SubElement(mkt, "AggregationScenarioDataCreditStates")
    ET.SubElement(acs, "NumberOfFactors").text = "0"

    # ── Write ─────────────────────────────────────────────────────────
    xml_str = _prettify(root)
    output_path.write_text(xml_str, encoding="utf-8")
    return output_path


# ── Sensitivity XML generation ────────────────────────────────────────────────

def generate_sensitivity_xml(
    market: MarketStructure,
    output_path: Path | None = None,
) -> Path:
    """
    Generate a minimal sensitivity.xml from the discovered MarketStructure.

    This produces a zero-shift sensitivity config (ShiftSize = 0.0001) that
    covers all market entities required by the stress test analytic.
    No ParConversion blocks are emitted — this is a simplified "zero" config
    sufficient for the stress test engine to resolve all risk factors.

    Parameters
    ----------
    market      : MarketStructure from parse()
    output_path : where to write; defaults to
                  config.ORE_INPUT_DIR / "sensitivity_agent.xml"
    """
    if output_path is None:
        output_path = config.ORE_INPUT_DIR / "sensitivity_agent.xml"
    output_path = Path(output_path)

    rate_tenors = ", ".join(config.STANDARD_RATE_TENORS)
    credit_tenors = ", ".join(config.STANDARD_CREDIT_TENORS)
    inflation_tenors = ", ".join(config.STANDARD_INFLATION_TENORS)

    root = ET.Element("SensitivityAnalysis")

    # ── Discount curves ───────────────────────────────────────────────
    dc_el = ET.SubElement(root, "DiscountCurves")
    for dc in market.discount_curves:
        curve = ET.SubElement(dc_el, "DiscountCurve", ccy=dc.currency)
        ET.SubElement(curve, "ShiftType").text = "Absolute"
        ET.SubElement(curve, "ShiftSize").text = "0.0001"
        ET.SubElement(curve, "ShiftScheme").text = "Forward"
        ET.SubElement(curve, "ShiftTenors").text = rate_tenors

    # ── Index curves ──────────────────────────────────────────────────
    ic_el = ET.SubElement(root, "IndexCurves")
    for idx in market.index_curves:
        curve = ET.SubElement(ic_el, "IndexCurve", index=idx.name)
        ET.SubElement(curve, "ShiftType").text = "Absolute"
        ET.SubElement(curve, "ShiftSize").text = "0.0001"
        ET.SubElement(curve, "ShiftScheme").text = "Forward"
        ET.SubElement(curve, "ShiftTenors").text = rate_tenors

    # ── Yield curves (empty) ──────────────────────────────────────────
    ET.SubElement(root, "YieldCurves")

    # ── FX spots ──────────────────────────────────────────────────────
    fx_el = ET.SubElement(root, "FxSpots")
    for pair in market.fx_pairs:
        foreign = pair[:3]
        domestic = pair[3:]
        sim_pair = domestic + foreign  # ORE convention
        spot = ET.SubElement(fx_el, "FxSpot", ccypair=sim_pair)
        ET.SubElement(spot, "ShiftType").text = "Relative"
        ET.SubElement(spot, "ShiftSize").text = "0.01"

    # ── Credit curves ─────────────────────────────────────────────────
    if market.default_curves:
        cc_el = ET.SubElement(root, "CreditCurves")
        for dc in market.default_curves:
            curve = ET.SubElement(cc_el, "CreditCurve", name=dc.name)
            ET.SubElement(curve, "Currency").text = dc.currency
            ET.SubElement(curve, "ShiftType").text = "Absolute"
            ET.SubElement(curve, "ShiftSize").text = "0.0001"
            ET.SubElement(curve, "ShiftScheme").text = "Forward"
            ET.SubElement(curve, "ShiftTenors").text = credit_tenors

    # ── CapFloor volatilities ─────────────────────────────────────────
    if market.capfloor_vols:
        cfv_el = ET.SubElement(root, "CapFloorVolatilities")
        for cv in market.capfloor_vols:
            vol = ET.SubElement(cfv_el, "CapFloorVolatility", key=cv.name)
            ET.SubElement(vol, "ShiftType").text = "Absolute"
            ET.SubElement(vol, "ShiftSize").text = "0.0001"
            ET.SubElement(vol, "ShiftExpiries").text = (
                "1Y, 2Y, 3Y, 5Y, 7Y, 10Y, 15Y, 20Y"
            )
            ET.SubElement(vol, "ShiftStrikes").text = (
                "-0.01, 0, 0.01, 0.02, 0.03, 0.04, 0.05"
            )
            ET.SubElement(vol, "Index").text = cv.name

    # ── Zero inflation index curves ───────────────────────────────────
    if market.inflation_indices:
        zi_el = ET.SubElement(root, "ZeroInflationIndexCurves")
        for zi in market.inflation_indices:
            curve = ET.SubElement(zi_el, "ZeroInflationIndexCurve", index=zi.name)
            ET.SubElement(curve, "ShiftType").text = "Absolute"
            ET.SubElement(curve, "ShiftSize").text = "0.0001"
            ET.SubElement(curve, "ShiftTenors").text = inflation_tenors

    # ── Equity spots ──────────────────────────────────────────────────
    if market.equity_curves:
        eq_el = ET.SubElement(root, "EquitySpots")
        for eq in market.equity_curves:
            spot = ET.SubElement(eq_el, "EquitySpot", equity=eq.name)
            ET.SubElement(spot, "ShiftType").text = "Relative"
            ET.SubElement(spot, "ShiftSize").text = "0.01"
            ET.SubElement(spot, "ShiftScheme").text = "Forward"

    # ── Global flags ──────────────────────────────────────────────────
    ET.SubElement(root, "ComputeGamma").text = "false"
    ET.SubElement(root, "UseSpreadedTermStructures").text = "true"

    xml_str = _prettify(root)
    output_path.write_text(xml_str, encoding="utf-8")
    return output_path


# ── Pretty-print MarketStructure ──────────────────────────────────────────────

def format_market_structure(ms: MarketStructure) -> str:
    """Return a human-readable summary of the discovered market structure."""
    lines = [
        f"Base currency: {ms.base_currency}",
        f"Currencies:    {', '.join(sorted(ms.currencies))}",
        "",
        f"Discount curves ({len(ms.discount_curves)}):",
    ]
    for c in ms.discount_curves:
        lines.append(f"  {c.currency:4s}  {c.name:30s}  {c.spec}")
    lines.append(f"\nIndex curves ({len(ms.index_curves)}):")
    for c in ms.index_curves:
        lines.append(f"  {c.currency:4s}  {c.name:30s}  {c.spec}")
    if ms.yield_curves:
        lines.append(f"\nYield curves ({len(ms.yield_curves)}):")
        for c in ms.yield_curves:
            lines.append(f"  {c.currency:4s}  {c.name:30s}  {c.spec}")
    lines.append(f"\nFX pairs ({len(ms.fx_pairs)}):")
    for p in ms.fx_pairs:
        lines.append(f"  {p}")
    if ms.equity_curves:
        lines.append(f"\nEquity curves ({len(ms.equity_curves)}):")
        for c in ms.equity_curves:
            lines.append(f"  {c.currency:4s}  {c.name:30s}  {c.spec}")
    if ms.default_curves:
        lines.append(f"\nDefault curves ({len(ms.default_curves)}):")
        for c in ms.default_curves:
            lines.append(f"  {c.currency:4s}  {c.name:30s}  {c.spec}")
    if ms.inflation_indices:
        lines.append(f"\nInflation indices ({len(ms.inflation_indices)}):")
        for c in ms.inflation_indices:
            lines.append(f"  {c.currency:4s}  {c.name:30s}  {c.spec}")
    return "\n".join(lines)
