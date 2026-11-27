"""Natural language interpretation with tool calling.

Real adapter: Azure OpenAI chat completions with function tools. Simulated adapter: deterministic Spanish
rules that emit the same tool-call structure. Both only choose a tool and arguments; the backend validates
and executes.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from app.agent import parsing as p
from app.core.config import get_settings


@dataclass
class ToolCall:
    name: str
    arguments: dict


@dataclass
class Interpretation:
    provider: str
    tool_call: ToolCall | None = None
    reply: str | None = None
    tokens: int | None = None


class LLMClient(Protocol):
    name: str

    def interpret(self, *, system: str, history: list[dict], user_text: str, tools: list[dict]) -> Interpretation:
        ...


class AzureOpenAIClient:
    name = "azure_openai"

    def __init__(self) -> None:
        from openai import AzureOpenAI

        s = get_settings()
        self.client = AzureOpenAI(azure_endpoint=s.azure_openai_endpoint, api_key=s.azure_openai_api_key,
                                  api_version=s.azure_openai_api_version, timeout=30, max_retries=2)
        self.deployment = s.azure_openai_deployment

    def interpret(self, *, system: str, history: list[dict], user_text: str, tools: list[dict]) -> Interpretation:
        messages = [{"role": "system", "content": system}, *history,
                    {"role": "user", "content": f"<mensaje_usuario>\n{user_text}\n</mensaje_usuario>"}]
        kwargs: dict = {"model": self.deployment, "messages": messages, "temperature": 0}
        if tools:
            kwargs.update(tools=tools, tool_choice="auto")
        resp = self.client.chat.completions.create(**kwargs)
        choice = resp.choices[0].message
        tokens = resp.usage.total_tokens if resp.usage else None
        if choice.tool_calls:
            call = choice.tool_calls[0]
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            return Interpretation(self.name, ToolCall(call.function.name, args), None, tokens)
        return Interpretation(self.name, None, choice.content, tokens)


class SimulatedLLMClient:
    """Rule-based interpreter for local development. Identified as 'simulated' in every record."""

    name = "simulated"

    def interpret(self, *, system: str, history: list[dict], user_text: str, tools: list[dict]) -> Interpretation:
        allowed = {t["function"]["name"] for t in tools}
        call = self._rules(user_text, allowed)
        if call is None or call.name not in allowed:
            return Interpretation(self.name, None, None)
        return Interpretation(self.name, call)

    @staticmethod
    def _fields(text: str) -> dict:
        out: dict = {}
        if (w := p.weight_kg(text)) is not None:
            out["weight_kg"] = str(w)
        if (s := p.sacks(text)) is not None:
            out["sacks"] = s
        if (sl := p.seal(text)) is not None:
            out["seal"] = sl
        if (pl := p.plate(text)) is not None:
            out["vehicle_plate"] = pl
        if (m := p.moisture(text)) is not None:
            out["moisture_pct"] = str(m)
        if (st := p.coffee_state(text)) is not None:
            out["coffee_state"] = st
        if (lc := p.lot_code(text)) is not None:
            out["lot_code"] = lc
        return out

    def _rules(self, text: str, allowed: set[str]) -> ToolCall | None:
        n = p.norm(text)
        if p.alert_code(text) and "justify_alert" in allowed:
            return ToolCall("justify_alert", {"alert_code": p.alert_code(text), "justification": text})
        if "update_pending_operation" in allowed:
            fields = self._fields(text)
            if fields:
                return ToolCall("update_pending_operation", fields)
        if any(k in n for k in ("donde va mi cafe", "donde esta mi cafe", "como va mi cafe", "mi cafe")):
            return ToolCall("query_my_coffee", {})
        if any(k in n for k in ("revision humana", "hablar con una persona", "asesor", "ayuda humana")):
            return ToolCall("request_human_review", {"reason": text})
        if ("lote" in n and any(k in n for k in ("arma", "crea", "consolida", "junta", "forma"))):
            codes = p.purchase_codes(text)
            args: dict = {"purchase_codes": codes} if codes else {"selection": "today"}
            for word, num in (("dos", 2), ("tres", 3), ("cuatro", 4), ("cinco", 5)):
                if f" {word} compras" in f" {n}":
                    args["expected_count"] = num
            return ToolCall("create_lot", args)
        if p.purchase_codes(text) and any(k in n for k in ("corrig", "correccion", "estaba mal", "error")):
            args = {"purchase_code": p.purchase_codes(text)[0], "reason": text}
            if (w := p.weight_kg(text)) is not None:
                args["new_weight_kg"] = str(w)
            return ToolCall("correct_event", args)
        intro, farm = p.introduction(text), p.farm_name(text)
        if intro and farm:
            return ToolCall("register_producer", {"name": intro, "farm_name": farm, "vereda": p.vereda(text),
                                                  "municipality": p.municipality(text)})
        lot = p.lot_code(text)
        if lot and any(k in n for k in ("estado", "donde", "como va", "consulta", "ubicacion")):
            return ToolCall("query_lot_status", {"lot_code": lot})
        fields = self._fields(text)
        weights = [str(w) for w in (p.to_decimal(m.group(1)) for m in p.WEIGHT_RE.finditer(text)) if w is not None]
        if any(k in n for k in ("trill", "transform")):
            return ToolCall("register_transformation", {**fields, "weights": weights})
        if any(k in n for k in ("despach", "salio", "sale el lote", "enviamos")):
            return ToolCall("register_dispatch", fields)
        if any(k in n for k in ("recibi", "recibimos", "llego", "llegaron")):
            return ToolCall("register_reception", fields)
        if lot:
            return ToolCall("query_lot_status", {"lot_code": lot})
        return None


@lru_cache
def get_llm_client() -> LLMClient:
    if get_settings().llm_provider == "azure":
        return AzureOpenAIClient()
    return SimulatedLLMClient()
