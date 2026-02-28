#!/usr/bin/env python3
"""Quick integration test for the generic schema refactoring."""

import config
import todaysmarket_analyzer
import stresstest_builder
import ore_runner
from pathlib import Path
from historical_scenarios import ScenarioKnowledgeBase

# 1. Test scenario loading
kb = ScenarioKnowledgeBase(config.DATA_DIR / "scenarios.json")
print(f"Loaded {len(kb)} scenarios")
print(f"First: {kb[0]['name']}")
print(f"Schema keys: {list(kb[0]['shifts'].keys())}")
print()

# 2. Test market structure parsing
ms = todaysmarket_analyzer.parse()
print(todaysmarket_analyzer.format_market_structure(ms))
print()

# 3. Test sector mapping
sector_map = todaysmarket_analyzer.load_sector_mapping()
print(f"Sector map entries: {len(sector_map)}")
for k, v in sector_map.items():
    print(f"  {k} -> {v}")
print()

# 4. Test equity resolution with first scenario
shifts = kb[0]["shifts"]
for eq in ms.equity_curves:
    s = todaysmarket_analyzer.resolve_equity_shift(eq, shifts, sector_map)
    print(f"Equity {eq.name} ({eq.currency}): shift={s:+.0%}")

# 5. Test credit resolution
for dc in ms.default_curves:
    c = todaysmarket_analyzer.resolve_credit_shifts(dc, shifts, sector_map)
    print(f"Credit {dc.name} ({dc.currency}): {c}")
print()

# 6. Build the stress test XML
path = stresstest_builder.build(shifts=shifts, market=ms, sector_map=sector_map)
print(f"Stress XML written to: {path}")

# 7. Validate XML
from xml.etree import ElementTree as ET
tree = ET.parse(path)
root = tree.getroot()
print(f"Root tag: {root.tag}")
stress_tests = root.findall("StressTest")
print(f"StressTests: {len(stress_tests)}")
for st in stress_tests:
    disc = st.findall(".//DiscountCurve")
    idx = st.findall(".//IndexCurve")
    eq = st.findall(".//EquitySpot")
    fx = st.findall(".//FxSpot")
    surv = st.findall(".//SurvivalProbability")
    print(f"  Discount curves: {len(disc)}")
    print(f"  Index curves:    {len(idx)}")
    print(f"  FX spots:        {len(fx)}")
    print(f"  Equity spots:    {len(eq)}")
    print(f"  Survival probs:  {len(surv)}")

print("\n✓ All imports and build OK!")

# 8. Build ore_agent.xml (stress-only ORE config)
ore_workspace = config.ORE_WORKSPACE
ore_agent_xml = stresstest_builder.build_ore_config(
    base_ore_xml=ore_workspace / "ore.xml",
    stress_config_file="agent_stress.xml",
)
print(f"\nORE agent config written to: {ore_agent_xml}")

# 9. Run ORE via Python bindings
csv_path = ore_runner.run(ore_xml=ore_agent_xml, workspace=ore_workspace)
print(f"ORE completed — output: {csv_path}")

# 10. Read and display stress test results
import pandas as pd
import io

with csv_path.open() as f:
    content = f.read().replace("#TradeId", "TradeId", 1)

df = pd.read_csv(io.StringIO(content))
df.columns = [c.strip() for c in df.columns]
df["PnL"] = df["Scenario NPV"] - df["Base NPV"]

print(f"\nStress test results ({len(df)} rows):")
print(f"  Scenarios: {df['ScenarioLabel'].unique().tolist()}")
print(f"  Total Base NPV:     {df['Base NPV'].sum():>14,.0f}")
print(f"  Total Stressed NPV: {df['Scenario NPV'].sum():>14,.0f}")
print(f"  Total P&L:          {df['PnL'].sum():>+14,.0f}")
print()
print(df[["TradeId", "Base NPV", "Scenario NPV", "PnL"]].to_string(index=False))

print("\n✓ Full pipeline (build + ORE run + output) OK!")
