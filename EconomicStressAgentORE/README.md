# Economic Scenario Stress Test Agent

An AI agent that maps a free-text economic scenario to similar historical scenarios,
derives market shifts, runs an ORE stress test, and summarises the P&L impact.

This is just educational purpose, I developed this agent to learn more about AI Agents
and how to integrate Open Source Risk Engine into an Agent.

The scenarios are mock and AI generated, as is most of the code.

## Workflow

```
User describes scenario
        │
        ▼
┌─────────────────────────┐
│  1. Scenario Analyzer    │  GPT-4 + 20-scenario knowledge base
│     (historical lookup)  │
└───────────┬─────────────┘
            │  structured JSON of market shifts
            ▼
┌─────────────────────────┐
│  2. Stress Test Builder  │  generates agent_stress.xml for ORE
└───────────┬─────────────┘
            │  ore_agent.xml + Input/agent_stress.xml
            ▼
┌─────────────────────────┐
│  3. ORE Runner           │  runs ORE (Python API)
└───────────┬─────────────┘
            │  Output/stresstest.csv
            ▼
┌─────────────────────────┐
│  4. Impact Summarizer    │  Markdown report + LLM narrative
└─────────────────────────┘
```

## Known Shortcomings & Shortcuts

This project is a proof-of-concept built for learning purposes. Several design
decisions were taken as shortcuts and would need to be rethought for any
production use.

### 1. Historical scenarios are mock data

The 20 historical episodes in `data/scenarios.json` are AI-generated
approximations, not rigorously sourced market data. In a real system these
would be replaced by:

- Curated, auditable data sets of actual market moves (sourced from market
  data providers or internal risk databases).
- Proper versioning and provenance tracking so every shift can be traced
  back to an observed market event.

### 2. The LLM produces the final shifts directly — not auditable

Currently the LLM receives the historical scenarios, picks the closest
matches, and returns a _weighted average_ of market shifts in a single step.
This is problematic because:

- **Non-reproducible**: the same prompt can yield different numbers across
  runs or model versions, making results impossible to audit.
- **Not explainable**: there is no transparent formula an auditor or
  regulator can inspect — the blending logic is a black box inside the model.

A better architecture would split the task in two:

1. **LLM step (qualitative)**: the model selects the _N_ closest historical
   scenarios and proposes a _severity multiplier_ (e.g. "80% of the 2008
   crisis combined with 50% of the Dot-com bust"). This output is
   human-readable and auditable.
2. **Deterministic step (quantitative)**: a macro-economic model or a simple rule-based mapping takes the selected scenarios and severity parameters
   as inputs and produces the final shift vector. Because the model is
   versioned code with fixed parameters, the output is fully reproducible,
   testable, and auditable.

This separation keeps the LLM's role limited to _judgement_ (scenario
matching and severity assessment) while all _numerical_ work is done by
auditable, deterministic code.

### 3. Other simplifications

- **Single stress scenario per run** — no support for running a grid of
  severities or multiple scenarios in one invocation.
- **No volatility or correlation shifts** — only spot-level shifts are
  applied; a real stress test would also shock implied vols, correlations,
  and basis spreads.
- **Flat extrapolation of tenor grids** — shift curves are linearly
  interpolated and flat-extrapolated, which may be too simplistic for
  far-out-of-grid tenors.
- **No validation against market bounds** — the LLM-generated shifts are
  not sanity-checked (e.g. negative rates below a floor, FX moves beyond
  historical extremes).
- **Toy portfolio** — the included ORE workspace has only a handful of
  trades;
- **Construction of simulation/stresstest/sensitivity config** is incomplete and can handle
  only a few risk factors (no volatilities, no commodity risk factors) and allow only a small range or products.

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

The `open-source-risk-engine` package provides the ORE Python bindings (`from ORE import *`).

### 2. Configure environment

```bash
cp .env.example .env
# then edit .env
```

`.env` keys:

| Key              | Description                     | Required |
| ---------------- | ------------------------------- | -------- |
| `OPENAI_API_KEY` | Your OpenAI API key             | Yes      |
| `OPENAI_MODEL`   | Model name (default: `gpt-5.2`) | No       |

### 3. ORE workspace

The agent expects the ORE workspace at `./oredata/` containing:

```
oredata/
├── ore.xml          ← main ORE config
├── Input/
│   ├── portfolio.xml
│   ├── marketdata.csv
│   ├── conventions.xml
│   ├── curveconfig.xml
│   ├── todaysmarket.xml
│   ├── simulation.xml
│   ├── sensitivity.xml
│   └── pricingengine.xml
└── Output/          ← cleaned and recreated on each run
```

The agent injects two files at runtime:

- `oredata/Input/agent_stress.xml` — generated stress scenario
- `oredata/ore_agent.xml` — stripped-down ore.xml (stress analytic only)

## Usage

```bash
# Basic usage
python agent.py --scenario "Giant monsters emerge from the ocean and destroy two major capitals in Europe and Asia simultaneously, triggering martial law, insurance system collapse, and a global flight to safety"

# With all options
python agent.py \
  --scenario "python agent.py --scenario "Giant monsters emerge from the ocean and destroy two major capitals in Europe and Asia simultaneously, triggering martial law, insurance system collapse, and a global flight to safety" \
  --ore-workspace ./oredata \
  --scenario-id my_scenario \
  --output report.md \
  --verbose
```

## Architecture

| File                       | Purpose                                                 |
| -------------------------- | ------------------------------------------------------- |
| `agent.py`                 | CLI orchestrator — ties all steps together              |
| `scenario_analyzer.py`     | LLM call — maps text to market shifts                   |
| `stresstest_builder.py`    | XML generator — writes ORE stress test config           |
| `ore_runner.py`            | ORE execution via Python API                            |
| `impact_summarizer.py`     | CSV parser + LLM narrative report                       |
| `historical_scenarios.py`  | `ScenarioKnowledgeBase` class — loads `scenarios.json`  |
| `todaysmarket_analyzer.py` | Parses todaysmarket.xml to discover curves and equities |
| `config.py`                | Paths, model settings, tenor grids                      |
| `data/scenarios.json`      | 20 historical episodes with structured shifts           |

## Market shift schema

Shifts are specified in a generic, multi-currency schema:

| Asset class | Schema key   | Value convention                         | ORE mapping                     |
| ----------- | ------------ | ---------------------------------------- | ------------------------------- |
| Rates       | `rates.CCY`  | Absolute (decimal, e.g. -0.015 = -150bp) | Discount + Index curves per ccy |
| FX          | `fx.PAIR`    | Absolute change in spot                  | FxSpot (inverted for ORE)       |
| Equity      | `equity.KEY` | Relative (e.g. -0.25 = -25%)             | EquitySpot                      |
| Credit      | `credit.KEY` | Absolute per tenor (widening positive)   | SurvivalProbability             |

Rate and credit shifts are interpolated onto the ORE tenor grid using
`ORE.LinearInterpolation` with flat extrapolation.

Equity and credit names are resolved via an optional sector mapping
(`sector_mapping.csv`) that maps trade-level names to scenario-level keys.

## Example output

```
╔══════════════════════════════════════════════════════════╗
║       Economic Scenario Stress Test Agent                ║
╚══════════════════════════════════════════════════════════╝

Analyzing scenario: "Giant monsters emerge from the ocean and destroy two major capitals in Europe and Asia simultaneously, triggering martial law, insurance system collapse, and a global flight to safety"

  ▶ Step 1/5  Analyzing scenario with LLM …
  ✓ Scenario analysis complete

Matched scenarios:
  • 2008 Global Financial Crisis (Sep 2008 – Mar 2009)
  • 2020 COVID-19 Crash (Feb – Mar 2020)
  • Eurozone Break-up (Tail Risk) (Hypothetical)

Reasoning: Simultaneous destruction of major capitals with martial law and insurance-system collapse implies an extreme, sudden global risk-off/liquidity shock (GFC/COVID-like) plus acute Europe-specific tail risk and EUR dislocation (Eurozone break-up proxy). Weighted blend emphasizes severe credit stress and safe-haven bid, with EUR underperformance; scaled up to reflect catastrophic severity beyond typical historical episodes.

Proposed market shifts:
  FX EURUSD: -0.1875
  Equity EUR: -63.7%
  Equity USD: -48.0%
  Rates EUR: 1Y -8bp  2Y -9bp  3Y -9bp  5Y -6bp  10Y -4bp  30Y -2bp
  Rates USD: 1Y -225bp  2Y -240bp  3Y -240bp  5Y -225bp  10Y -180bp  30Y -135bp
  Credit EUR: 1Y +270bp  2Y +375bp  3Y +435bp  5Y +495bp  10Y +465bp
  Credit USD: 1Y +225bp  2Y +300bp  3Y +360bp  5Y +420bp  10Y +375bp
  Credit Sovereign: 1Y +675bp  2Y +945bp  3Y +1080bp  5Y +1215bp  10Y +1080bp

  ▶ Step 2/5  Parsing todaysmarket.xml …
  ✓ Discovered 2 currencies, 2 discount curves, 2 equities, 1 credit names

  ▶ Step 3/5  Generating ORE stress test XML …
  ✓ Written: /Users/matthiasgroncki/quant-dev/IPythonScripts/EconomicStressAgentORE/oredata/Input/agent_stress.xml
  ✓ Written: /Users/matthiasgroncki/quant-dev/IPythonScripts/EconomicStressAgentORE/oredata/ore_agent.xml

  ▶ Step 4/5  Running ORE …
Running ORE with config: ore_agent.xml from workspace: /Users/matthiasgroncki/quant-dev/IPythonScripts/EconomicStressAgentORE/oredata
Loading inputs                                    OK
Requested analytics                               STRESS
StressTestAnalytic: Build Market                  OK
StressTestAnalytic: Build Portfolio               OK
Risk: Stress Test Report                          OK
Writing reports...                                OK
Writing cubes...                                  OK
run time: 0.180000 sec
ORE done.
  ✓ ORE completed. Results: /Users/matthiasgroncki/quant-dev/IPythonScripts/EconomicStressAgentORE/oredata/Output/stresstest.csv

  ▶ Step 5/5  Generating impact report …
  ✓ Report ready

════════════════════════════════════════════════════════════
  Portfolio Stress Test Impact Report
════════════════════════════════════════════════════════════

  TOTAL P&L: -20,452,247 EUR  [▼ LOSS]

┌───────────────┬────────────┬──────────────┬─────────────┐
│ Trade         │   Base NPV │ Stressed NPV │  P&L Impact │
├───────────────┼────────────┼──────────────┼─────────────┤
│ XccySwap      │    268,878 │  -18,241,162 │ -18,510,040 │
│ EquityCFD_USD │     76,647 │   -3,119,320 │  -3,195,967 │
│ EquityCFD_EUR │  1,263,244 │   -1,709,064 │  -2,972,308 │
│ EUR6MSwap     │  5,924,804 │    5,774,330 │    -150,474 │
│ CDS           │ -6,405,864 │   -2,029,322 │  +4,376,542 │
├═══════════════┼════════════┼══════════════┼═════════════┤
│ TOTAL         │  1,127,710 │  -19,324,538 │ -20,452,247 │
└───────────────┴────────────┴──────────────┴─────────────┘

────────────────────────────────────────────────────────────
  Narrative Summary
────────────────────────────────────────────────────────────

Under the “global flight to safety” shock—EURUSD down 0.1875 (absolute), equities down 63.7% in EUR and 48.0% in USD, sharp USD rate rallies (down 225–240bp out to 5Y and down 180bp at 10Y), and severe spread widening (EUR credit +270bp to +495bp, USD credit +225bp to +420bp, sovereign credit +675bp to +1,215bp)—the portfolio moves from a base NPV of EUR 1,127,710 to a stressed NPV of EUR -19,324,538. This is a total P&L impact of EUR -20,452,247, indicating the portfolio is highly exposed to combined FX dislocation, equity crash risk, and cross-currency/rates basis dynamics under extreme systemic stress.

The loss is overwhelmingly driven by the cross-currency and equity risk factors. The XccySwap contributes EUR -18,510,040 of the total drawdown, with its valuation swinging from EUR 268,878 to EUR -18,241,162, consistent with a regime where USD funding stress and large EURUSD moves dominate outcomes. Equity risk is the next major driver: EquityCFD_USD loses EUR -3,195,967 (EUR 76,647 to EUR -3,119,320) and EquityCFD_EUR loses EUR -2,972,308 (EUR 1,263,244 to EUR -1,709,064), reflecting the -48.0% and -63.7% equity shocks compounded by the EURUSD drop for USD-denominated exposure when reported in EUR.

Offsetting gains come primarily from credit protection. The CDS position generates EUR +4,376,542 (from EUR -6,405,864 to EUR -2,029,322), benefiting from the very large credit and sovereign spread widening (up to +495bp in EUR credit and +1,215bp in sovereign spreads at 5Y). Rates contribute only marginally: the EUR6MSwap loses EUR -150,474 (EUR 5,924,804 to EUR 5,774,330), consistent with relatively small EUR curve shifts (single-digit bp rally across tenors) compared with the much larger moves in USD rates and credit.

Overall, the stress test indicates a concentrated tail risk profile: the portfolio’s protection via CDS is meaningful but insufficient against the dominant cross-currency swap exposure and equity beta in a simultaneous FX break and equity crash. The result suggests the portfolio is effectively short extreme funding/FX dislocation (via the XccySwap) and long risk assets (via the equity CFDs), with credit hedges providing partial convexity but not enough to prevent a large negative NPV under systemic shock. The key risk interpretation is that diversification breaks down in this scenario and the portfolio’s P&L is governed by a small number of positions whose sensitivities amplify precisely when liquidity and basis risks are most stressed.
```
