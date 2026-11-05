"""Turn the Cortex Agent's server-sent events into one answer the page can draw.

Pure: no Streamlit, no network. tests/test_app_answer.py replays a captured live stream through it.

What the stream looks like (captured 2026-11-05): ~40s of status, thinking and tool events, then
the answer arrives as numbered content blocks, interleaved text, table and chart:

    text (ci 12) -> table (ci 13) -> text (ci 14) -> chart (ci 15) -> text "Source: ..." (ci 16)

so blocks are kept by content_index and drawn in that order, never grouped by kind.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import pandas as pd

# What the person sees while they wait. The agent spends 30-60s before writing a word, so the
# wait has to show progress that is true: each step is entered only on the event that proves it.
STEPS = ("understand", "data", "query", "chart", "write")
STEP_LABELS = {
    "understand": "Understanding your question",
    "data": "Finding the right IPEDS tables",
    "query": "Running the query on federal IPEDS data",
    "chart": "Drawing a chart",
    "write": "Writing the answer",
}

TIMED_OUT = "reached the time limit"


@dataclass
class Block:
    kind: str                       # text | table | chart
    text: str = ""
    table: pd.DataFrame | None = None
    chart: dict | None = None


@dataclass
class Answer:
    blocks: dict[int, Block] = field(default_factory=dict)
    sql: list[str] = field(default_factory=list)
    suggested: list[str] = field(default_factory=list)
    step: str = "understand"
    error: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    done: bool = False

    # -------------------------------------------------------------- events
    def apply(self, event: str, data: dict) -> None:
        handler = getattr(self, "_on_" + event.replace(".", "_"), None)
        if handler:
            handler(data)

    def _advance(self, step: str) -> None:
        if STEPS.index(step) > STEPS.index(self.step):
            self.step = step

    def _on_response_tool_use(self, d: dict) -> None:
        kind = d.get("type") or d.get("name")
        if kind == "system_agentic_semantic_context":
            self._advance("data")
        elif kind == "system_execute_sql":
            self._advance("query")
            sql = (d.get("input") or {}).get("sql")
            if sql:
                self.sql.append(sql.strip())
        elif kind == "data_to_chart" or (d.get("input") or {}).get("skill_name") == "chart_instructions":
            self._advance("chart")

    def _on_response_status(self, d: dict) -> None:
        if d.get("status") == "proceeding_to_answer":
            self._advance("write")

    def _on_response_text_delta(self, d: dict) -> None:
        self._advance("write")
        b = self.blocks.setdefault(d.get("content_index", 0), Block("text"))
        b.text += d.get("text", "")

    def _on_response_text(self, d: dict) -> None:
        # The completed block is authoritative over the deltas that built it.
        self.blocks[d.get("content_index", 0)] = Block("text", text=d.get("text", ""))

    def _on_response_table(self, d: dict) -> None:
        df = result_set_to_frame(d.get("result_set") or {})
        if df is not None:
            self.blocks[d.get("content_index", 0)] = Block("table", table=df)

    def _on_response_chart(self, d: dict) -> None:
        try:
            spec = json.loads(d.get("chart_spec") or "{}")
        except json.JSONDecodeError:
            return
        if spec:
            self.blocks[d.get("content_index", 0)] = Block("chart", chart=spec)

    def _on_response_suggested_queries(self, d: dict) -> None:
        self.suggested = [q["query"] for q in d.get("suggested_queries", []) if q.get("query")][:3]

    def _on_response(self, d: dict) -> None:
        for t in ((d.get("metadata") or {}).get("usage") or {}).get("tokens_consumed", []):
            self.input_tokens = (self.input_tokens or 0) + int((t.get("input_tokens") or {}).get("total", 0))
            self.output_tokens = (self.output_tokens or 0) + int((t.get("output_tokens") or {}).get("total", 0))
        self.done = True

    def _on_error(self, d: dict) -> None:
        self.error = d.get("message") or json.dumps(d)[:500]

    def _on_done(self, d: dict) -> None:
        self.done = True

    # -------------------------------------------------------------- reading
    def ordered(self) -> list[Block]:
        return [self.blocks[i] for i in sorted(self.blocks)]

    @property
    def text(self) -> str:
        return "".join(b.text for b in self.ordered() if b.kind == "text").strip()

    @property
    def ok(self) -> bool:
        """Worth keeping in the conversation history the agent sees on the next turn."""
        return not self.error and bool(self.text) and TIMED_OUT not in self.text


# ------------------------------------------------------------------ tables
_YEARish = re.compile(r"(^|_)(year|fall|cohort|ipeds_year|aid_year)($|_)", re.I)
_ACRONYMS = {"sat", "act", "hbcu", "ipeds", "pell", "ft", "pt", "us", "r1", "r2", "cip", "id", "unitid", "nces"}


_MONEY = re.compile(r"(price|cost|tuition|aid|grant|loan|amount|dollars|fees)", re.I)
_INCOME_BAND = re.compile(r"income_(\d+)_(\d+)k", re.I)


def is_money_column(name: str) -> bool:
    return bool(_MONEY.search(name)) and not re.search(r"(pct|percent|share|rate|count|number|students|recipients)", name, re.I)


def label(col: str) -> str:
    """TOTAL_ENROLLMENT -> Total enrollment; PCT_PELL -> % Pell; NET_PRICE_INCOME_0_30K -> Net price income $0-30k."""
    col = _INCOME_BAND.sub(lambda m: f"income_${m.group(1)}\u2013{m.group(2)}k", col)
    words = col.lower().split("_")
    out = []
    for w in words:
        if w in ("pct", "percent"):
            out.append("%")
        elif w in _ACRONYMS:
            out.append(w.upper() if w not in ("pell",) else "Pell")
        else:
            out.append(w)
    text = " ".join(out)
    return text[:1].upper() + text[1:]


def is_year_column(name: str, s: pd.Series) -> bool:
    if not _YEARish.search(name) or not pd.api.types.is_integer_dtype(s):
        return False
    vals = s.dropna()
    return vals.empty or bool(((vals >= 1900) & (vals <= 2100)).all())


def result_set_to_frame(rs: dict) -> pd.DataFrame | None:
    meta = (rs.get("resultSetMetaData") or {}).get("rowType") or []
    if not meta:
        return None
    df = pd.DataFrame(rs.get("data") or [], columns=[c["name"] for c in meta])
    for c in meta:
        name, typ = c["name"], (c.get("type") or "").lower()
        if typ in ("fixed", "real", "float", "number", "decimal"):
            num = pd.to_numeric(df[name], errors="coerce")
            if typ == "fixed" and not c.get("scale"):
                num = num.astype("Int64")
            df[name] = num
        elif typ == "boolean":
            df[name] = df[name].map({"true": True, "false": False, "TRUE": True, "FALSE": False})
    return df


# ------------------------------------------------------------------ text
def split_source(text: str) -> tuple[str, str | None]:
    """Pull the closing "Source: IPEDS (NCES), ..." line out so it can be drawn as a citation."""
    m = re.search(r"\n*\s*(Source:\s*IPEDS[^\n]*)\s*$", text)
    if not m:
        return text, None
    return text[: m.start()].rstrip(), m.group(1).strip()


def markdown_safe(text: str) -> str:
    """Streamlit markdown treats $...$ as LaTeX; "$9,219 versus $17,372" would render as math."""
    return re.sub(r"(?<!\\)\$", r"\\$", text)
