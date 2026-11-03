"""Optional local LLM narration via Ollama, with a grounding gate.

The LLM only rewrites already-retrieved evidence into prose. Its output is accepted only if
(1) every citation refers to a real evidence id, (2) it cites at least two items and
(3) every multi-digit number it states appears somewhere in the evidence. Otherwise the
caller falls back to the deterministic narrative, and the report records why.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from aegis.config import Settings
from aegis.observability.logging import get_logger

log = get_logger(__name__)
_CITATION = re.compile(r"\[(E\d+)\]")
_NUMBER = re.compile(r"(?<![\w.])(\d[\d,]*\.?\d*)")


@dataclass
class NarrationResult:
    text: str | None
    model: str | None
    rejected_reason: str | None = None


def ollama_available(settings: Settings) -> bool:
    if not settings.ollama_enabled:
        return False
    try:
        r = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=2.0)
        names = {m.get("name") for m in r.json().get("models", [])}
        return r.status_code == 200 and settings.ollama_model in names
    except Exception:
        return False


def build_prompt(evidence: list[dict[str, Any]], indicators: list[dict[str, Any]], priority: str) -> str:
    compact = [{k: e[k] for k in ("id", "title", "summary", "data")} for e in evidence]
    return (
        "You are assisting a fraud analyst reviewing a SIMULATED transaction. Write a concise "
        "investigation narrative of 4-6 sentences. Use ONLY facts present in the evidence JSON. "
        "Cite evidence ids in square brackets like [E1] after every factual claim. Do not invent "
        "numbers, names or events. Do not make a final fraud determination; recommend human review.\n\n"
        f"Assigned review priority: {priority}\n"
        f"Indicators: {json.dumps(indicators, default=str)}\n"
        f"Evidence: {json.dumps(compact, default=str)}\n\nNarrative:"
    )


def validate_grounding(text: str, evidence: list[dict[str, Any]]) -> str | None:
    ids = {e["id"] for e in evidence}
    cited = set(_CITATION.findall(text))
    if len(cited) < 2:
        return "fewer than two evidence citations"
    if unknown := cited - ids:
        return f"cites unknown evidence ids {sorted(unknown)}"
    haystack = json.dumps(evidence, default=str).replace(",", "")
    for raw in _NUMBER.findall(_CITATION.sub("", text)):
        num = raw.replace(",", "").rstrip(".")
        if len(num.replace(".", "")) >= 2 and num not in haystack:
            return f"states number {raw!r} that is not present in the evidence"
    return None


def narrate(
    settings: Settings, evidence: list[dict[str, Any]], indicators: list[dict[str, Any]], priority: str
) -> NarrationResult:
    try:
        r = httpx.post(
            f"{settings.ollama_base_url}/api/generate",
            timeout=settings.ollama_timeout_s,
            json={
                "model": settings.ollama_model,
                "prompt": build_prompt(evidence, indicators, priority),
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 350},
            },
        )
        r.raise_for_status()
        text = str(r.json().get("response", "")).strip()
    except Exception as exc:
        log.warning("ollama_failed", error=str(exc))
        return NarrationResult(None, settings.ollama_model, f"LLM call failed: {exc.__class__.__name__}")
    problem = validate_grounding(text, evidence)
    if problem:
        log.info("llm_narrative_rejected", reason=problem)
        return NarrationResult(None, settings.ollama_model, f"LLM output failed grounding check: {problem}")
    return NarrationResult(text, settings.ollama_model)
