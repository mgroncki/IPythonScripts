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

| Key              | Description                   | Required |
| ---------------- | ----------------------------- | -------- |
| `OPENAI_API_KEY` | Your OpenAI API key           | Yes      |
| `OPENAI_MODEL`   | Model name (default: `gpt-4`) | No       |

### 3. ORE workspace

The agent expects the ORE workspace at `./OREDir/` containing:

```
OREDir/
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
└── Output/          ← auto-created by ORE
```

The agent injects two files at runtime:

- `OREDir/Input/agent_stress.xml` — generated stress scenario
- `OREDir/ore_agent.xml` — stripped-down ore.xml (stress analytic only)

## Usage

```bash
# Basic usage
python agent.py --scenario "A sudden European banking crisis with contagion fears"

# With all options
python agent.py \
  --scenario "A sudden European banking crisis with contagion fears" \
  --ore-workspace ./OREDir \
  --scenario-id my_scenario \
  --output report.md \
  --verbose
```

## Architecture

| File                      | Purpose                                       |
| ------------------------- | --------------------------------------------- |
| `agent.py`                | CLI orchestrator — ties all steps together    |
| `scenario_analyzer.py`    | LLM call — maps text to market shifts         |
| `stresstest_builder.py`   | XML generator — writes ORE stress test config |
| `ore_runner.py`           | ORE execution (Python API or subprocess)      |
| `impact_summarizer.py`    | CSV parser + LLM narrative report             |
| `historical_scenarios.py` | Knowledge base of 20 historical episodes      |
| `config.py`               | Paths, model settings, curve grids            |

## Market entities handled

| Asset class   | Scenario key | ORE name                       |
| ------------- | ------------ | ------------------------------ |
| FX            | `EURUSD`     | `EURUSD` (absolute shift)      |
| Euro equities | `SX5E`       | `RIC:.STOXX50`                 |
| US equities   | `SPX`        | `RIC:.SPX`                     |
| EUR rates     | `rates_eur`  | EUR-ESTER + EUR discount curve |
| USD rates     | `rates_usd`  | USD-SOFR + USD discount curve  |

Rate shifts are specified at **1Y, 2Y, 5Y, 10Y, 30Y** and interpolated onto
the full ORE tenor grid using piecewise-linear interpolation.

## Example output

```
╔══════════════════════════════════════════════════════════╗
║       Economic Scenario Stress Test Agent                ║
╚══════════════════════════════════════════════════════════╝

Analyzing scenario: "A sudden European banking crisis with contagion fears"

  ▶ Step 1/4  Analyzing scenario with LLM …
  ✓ Scenario analysis complete

Matched scenarios:
  • 2010-2012 European Sovereign Debt Crisis
  • 2023 US Regional Banking Crisis

EURUSD   : -0.0700 (absolute)
SX5E     : -19.0%
SPX      : -8.5%
EUR rates: 1Y -8bp  2Y -10bp  5Y -9bp  10Y -7bp  30Y -4bp
USD rates: 1Y -8bp  2Y -12bp  5Y -14bp  10Y -12bp  30Y -8bp

  ▶ Step 2/4  Generating ORE stress test XML …
  ▶ Step 3/4  Running ORE …
  ▶ Step 4/4  Generating impact report …

════════════════════════════════════════════════════════════
  Portfolio Stress Test Impact Report
════════════════════════════════════════════════════════════

**TOTAL P&L: +92,000 EUR  [GAIN]**

| Trade       | Base NPV   | Stressed NPV | P&L Impact  |
|-------------|------------|--------------|-------------|
| CDS         | -64,059    | -63,293      | +766        |
| XccySwap    | 268,878    | 230,964      | -37,914     |
| EUR6MSwap   | 5,924,804  | 5,867,079    | -57,725     |
| ...         |            |              |             |
| **TOTAL**   | ...        | ...          | **+92,000** |
```
