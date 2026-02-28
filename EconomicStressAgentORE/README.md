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
python agent.py --scenario "A sudden European banking crisis with contagion fears"

# With all options
python agent.py \
  --scenario "A sudden European banking crisis with contagion fears" \
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
python agent.py -s "world wide AI mass lay offs for high income jobs"

╔══════════════════════════════════════════════════════════╗
║       Economic Scenario Stress Test Agent                ║
╚══════════════════════════════════════════════════════════╝

Analyzing scenario: "world wide AI mass lay offs for high income jobs"

  ▶ Step 1/5  Analyzing scenario with LLM …
  ✓ Scenario analysis complete

Matched scenarios:
  • 2001 Dot-com Bust (Mar 2000 – Oct 2002)
  • 2015 China Devaluation / EM Shock (Aug – Sep 2015)
  • 2011 US Debt-Ceiling Crisis / S&P Downgrade (Jul – Aug 2011)

Reasoning: A worldwide AI-driven wave of layoffs in high-income (white-collar/tech-heavy) jobs is most analogous to a tech-led equity drawdown with growth fears and policy easing (dot-com), with an added global risk-off/flight-to-quality component (2015, 2011). Severity is set to moderate-to-severe but below 2008: large equity hit (especially tech), meaningful rate declines, and moderate credit widening; USD benefits as a relative safe haven so EURUSD falls.

Proposed market shifts:
  FX EURUSD: -0.0126
  Equity EUR: -30.8%
  Equity USD: -25.2%
  Equity Tech: -45.0%
  Rates EUR: 1Y -105bp  2Y -99bp  3Y -80bp  5Y -84bp  10Y -84bp  30Y -63bp
  Rates USD: 1Y -210bp  2Y -196bp  3Y -161bp  5Y -154bp  10Y -126bp  30Y -84bp
  Credit EUR: 1Y +35bp  2Y +49bp  3Y +60bp  5Y +67bp  10Y +56bp
  Credit USD: 1Y +49bp  2Y +63bp  3Y +77bp  5Y +88bp  10Y +74bp

  ▶ Step 2/5  Parsing todaysmarket.xml …
  ✓ Discovered 2 currencies, 2 discount curves, 2 equities, 1 credit names

  ▶ Step 3/5  Generating ORE stress test XML …
  ✓ Written: /Users/matthiasgroncki/quant-dev/IPythonScripts/EconomicStressAgentORE/oredata/Input/agent_stress.xml
  ✓ Written: /Users/matthiasgroncki/quant-dev/IPythonScripts/EconomicStressAgentORE/oredata/ore_agent.xml

  ▶ Step 4/5  Running ORE …
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

  TOTAL P&L: -6,614,962 EUR  [▼ LOSS]

┌────────────────────────────┬────────────┬──────────────┬────────────┐
│ Trade                      │   Base NPV │ Stressed NPV │ P&L Impact │
├────────────────────────────┼────────────┼──────────────┼────────────┤
│ EUR6MSwap                  │  5,924,804 │    4,415,089 │ -1,509,715 │
│ EquityCFD_USD              │     76,647 │   -1,359,666 │ -1,436,313 │
│ EquityCFD_EUR              │  1,263,244 │     -172,789 │ -1,436,033 │
│ XccySwap                   │    268,878 │   -1,027,997 │ -1,296,875 │
│ Cap                        │  4,988,927 │    4,045,146 │   -943,781 │
│ ZeroCouponInflationSwapEUR │    -20,433 │      -21,311 │       -878 │
│ CDS                        │    -64,059 │      -55,424 │     +8,635 │
├════════════════════════════┼════════════┼══════════════┼════════════┤
│ TOTAL                      │ 12,438,009 │    5,823,047 │ -6,614,962 │
└────────────────────────────┴────────────┴──────────────┴────────────┘

────────────────────────────────────────────────────────────
  Narrative Summary
────────────────────────────────────────────────────────────

The “AI mass layoffs in high‑income jobs” scenario produces a severe risk‑off shock across equities and a strong rally in core rates, alongside widening credit spreads and a modest EURUSD move. Equities fall sharply (EUR equities -30.8%, USD equities -25.2%, and Tech -45.0%), while rates decline materially (EUR down 63–105bp across 1Y–30Y; USD down 84–210bp across 1Y–30Y). Credit spreads widen in both regions (EUR +35–67bp out to 10Y; USD +49–88bp out to 10Y). Under these combined shifts, portfolio NPV drops from EUR 12,438,009 to EUR 5,823,047, for a total P&L impact of -EUR 6,614,962 (about -53% of base NPV).

Losses are concentrated in equity and rates/FX-sensitive positions. The two equity CFD positions are the largest equity-driven detractors: EquityCFD_USD loses -EUR 1,436,313 (from EUR 76,647 to -EUR 1,359,666) and EquityCFD_EUR loses -EUR 1,436,033 (from EUR 1,263,244 to -EUR 172,789), consistent with the large equity drawdowns in both currencies. The rates rally and cross-currency dynamics also contribute heavily: the EUR6MSwap loses -EUR 1,509,715 (from EUR 5,924,804 to EUR 4,415,089) and the XccySwap loses -EUR 1,296,875 (from EUR 268,878 to -EUR 1,027,997), indicating significant exposure to curve moves and/or basis/FX interactions (EURUSD shifts by -0.0126 in absolute terms). The Cap position also detracts -EUR 943,781 (from EUR 4,988,927 to EUR 4,045,146), suggesting the scenario’s large rate move and volatility/convexity effects are adverse for this structure despite the directionally lower yields.

Offsets are limited and primarily credit-related. The CDS position gains EUR 8,635 (from -EUR 64,059 to -EUR 55,424), consistent with credit spread widening improving the value of protection, but the magnitude is small relative to the equity and rates-driven losses. The ZeroCouponInflationSwapEUR is essentially flat (-EUR 878), providing negligible diversification in this shock. Overall, the risk interpretation is that the portfolio is materially exposed to a synchronized risk-off regime where equities reprice lower and rates rally sharply; credit hedging is present but insufficient in size to counteract the dominant equity and rates/cross-currency losses, leaving the portfolio vulnerable to macro shocks that combine growth fears, policy-rate cuts, and widening spreads.
```
