"""
Historical economic scenarios knowledge base.

Loads scenario data from a JSON file and provides structured access
for the scenario analyser and stress-test builder.

Each scenario has the **generic schema**::

    shifts:
      rates:   { CCY: { tenor: abs_shift } }
      fx:      { PAIR: abs_shift }
      equity:  { CCY_or_sector: relative_shift }
      credit:  { CCY_or_sector: { tenor: abs_shift } }

* Rates / credit: absolute change (decimal, e.g. -0.015 = -150 bps).
* FX: absolute change in spot (e.g. -0.10 means spot drops by 0.10).
* Equity: relative change (e.g. -0.25 = -25 %).
"""

from __future__ import annotations

import json
from pathlib import Path


class ScenarioKnowledgeBase:
    """Immutable collection of historical stress scenarios loaded from JSON."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        if not self._path.exists():
            raise FileNotFoundError(f"Scenario file not found: {self._path}")
        self._scenarios: list[dict] = self._load()

    # -- loading -------------------------------------------------------------

    def _load(self) -> list[dict]:
        with open(self._path, "r") as fh:
            return json.load(fh)

    # -- public accessors ----------------------------------------------------

    @property
    def scenarios(self) -> list[dict]:
        """Return the raw list of scenario dicts."""
        return self._scenarios

    def __len__(self) -> int:
        return len(self._scenarios)

    def __getitem__(self, index: int) -> dict:
        return self._scenarios[index]

    def __iter__(self):
        return iter(self._scenarios)

    # -- formatting ----------------------------------------------------------

    @staticmethod
    def _fmt_tenor_dict(d: dict[str, float], unit: str = "bps") -> str:
        """Format a {tenor: shift} dict for display."""
        return " / ".join(
            f"{k}: {v * 10000:+.0f}" if unit == "bps" else f"{k}: {v:+.0%}"
            for k, v in d.items()
        )

    def get_scenarios_text(self) -> str:
        """Return a formatted text dump of all scenarios for LLM context."""
        lines: list[str] = []
        for i, s in enumerate(self._scenarios, 1):
            lines.append(f"### {i}. {s['name']} ({s['period']})")
            lines.append(s["description"])
            sh = s["shifts"]

            if "fx" in sh:
                for pair, v in sh["fx"].items():
                    lines.append(f"  FX {pair}: {v:+.2f}")

            if "equity" in sh:
                for key, v in sh["equity"].items():
                    lines.append(f"  Equity {key}: {v:+.0%}")

            if "rates" in sh:
                for ccy, tenors in sh["rates"].items():
                    lines.append(
                        f"  Rates {ccy} (bps): {self._fmt_tenor_dict(tenors)}"
                    )

            if "credit" in sh:
                for key, tenors in sh["credit"].items():
                    lines.append(
                        f"  Credit {key} (bps): {self._fmt_tenor_dict(tenors)}"
                    )

            lines.append("")
        return "\n".join(lines)
