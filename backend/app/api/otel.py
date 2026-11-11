"""OpenTelemetry OTLP/HTTP(JSON) trace 接入。

POST /api/v1/otel/v1/traces   (X-API-Key 绑定项目)
支持 GenAI 语义约定（gen_ai.*）与 OpenInference 约定（openinference.span.kind），
未知属性收敛进 span.metadata。
"""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Project, Span, Trace
from ..services.cost import estimate_cost
from .deps import get_project

router = APIRouter(prefix="/api/v1/otel", tags=["otel"])

_KIND_MAP = {
    "LLM": "llm", "TOOL": "tool", "RETRIEVER": "retrieval",
    "AGENT": "agent", "CHAIN": "chain", "EMBEDDING": "llm",
}


def _hex_to_uuid(hex_str: str, pad: bool = False) -> uuid.UUID:
    """OTLP 的 traceId(32hex)/spanId(16hex) → 内部 UUID 主键。"""
    h = (hex_str or "").strip().lower().replace("-", "")
    if pad and len(h) == 16:
        h = h + h  # spanId 扩展为 32 位，保持确定性
    return uuid.UUID(hex=h)


def _attrs_to_dict(attrs) -> dict:
    """OTLP AnyValue attribute 列表 → 平铺 dict。"""
    out = {}
    for a in attrs or []:
        k = a.get("key")
        v = a.get("value") or {}
        for tk in ("stringValue", "boolValue", "intValue", "doubleValue"):
            if tk in v:
                val = v[tk]
                if tk == "intValue":
                    # OTLP JSON 的 int64 序列化为字符串
                    val = int(val)
                out[k] = val
                break
        else:
            if "arrayValue" in v:
                out[k] = [self_v.get("stringValue", self_v) for self_v in
                          (item.get("value", {}) for item in v["arrayValue"].get("values", []))]
            elif "kvlistValue" in v:
                out[k] = _attrs_to_dict(v["kvlistValue"].get("values", []))
            else:
                out[k] = None
    return out


def _pick(d: dict, *keys):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _parse_ns(ns: int) -> datetime:
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)


def _genai_messages(attrs: dict):
    """gen_ai.prompt.{i}.content / gen_ai.completion.{i}.content → (input_msgs, output_msgs)。"""
    ins, outs = [], []
    for k, v in attrs.items():
        parts = k.split(".")
        # gen_ai.prompt.{i}.content / gen_ai.completion.{i}.content（4 段）
        if len(parts) == 4 and parts[0] == "gen_ai" and parts[1] in ("prompt", "completion") and parts[3] == "content":
            try:
                idx = int(parts[2])
            except ValueError:
                continue
            role = attrs.get(f"gen_ai.{parts[1]}.{idx}.role")
            item = {"role": role or ("user" if parts[1] == "prompt" else "assistant"),
                    "content": str(v)}
            (ins if parts[1] == "prompt" else outs).append((idx, item))
    return ([m for _, m in sorted(ins)] or None), ([m for _, m in sorted(outs)] or None)


def convert_resource_spans(doc: dict) -> list[dict]:
    """OTLP JSON → 内部 trace 载荷列表（[{name, status, start, end, spans:[...]}]）。"""
    traces: dict[str, dict] = {}
    for rs in doc.get("resourceSpans", []):
        resource = _attrs_to_dict((rs.get("resource") or {}).get("attributes"))
        system = _pick(resource, "gen_ai.system", "service.name") or ""
        for ss in rs.get("scopeSpans", []):
            for sp in ss.get("spans", []):
                trace_id_hex = sp.get("traceId")
                if not trace_id_hex:
                    continue
                trace = traces.setdefault(trace_id_hex, {
                    "name": resource.get("service.name") or "otel-trace",
                    "status": "ok", "error": None,
                    "start_time": None, "end_time": None,
                    "spans": [], "trace_id_hex": trace_id_hex,
                })
                attrs = _attrs_to_dict(sp.get("attributes"))
                kind_prop = str(_pick(attrs, "openinference.span.kind", "gen_ai.span.kind") or "").upper()
                span_type = _KIND_MAP.get(kind_prop, "llm" if attrs.get("gen_ai.request.model") else "chain")
                start = _parse_ns(sp["startTimeUnixNano"])
                end = _parse_ns(sp["endTimeUnixNano"]) if sp.get("endTimeUnixNano") else start
                is_error = sp.get("status", {}).get("code") == 2 or attrs.get("error") is True
                err_text = sp.get("status", {}).get("message") or None

                span_type_eff = span_type
                input_val = _pick(attrs, "gen_ai.prompt", "llm.input_messages", "input.value", "input")
                output_val = _pick(attrs, "gen_ai.completion", "llm.output_messages", "output.value", "output")
                if isinstance(input_val, str):
                    input_val = {"text": input_val}
                if isinstance(output_val, str):
                    output_val = {"text": output_val}
                if is_error:
                    input_val = input_val or {}
                    output_val = {"error": err_text or "error"}
                    span_type_eff = span_type
                in_msgs, out_msgs = _genai_messages(attrs)
                if span_type == "llm":
                    input_val = in_msgs or input_val
                    if not is_error:
                        if out_msgs:
                            output_val = out_msgs if len(out_msgs) > 1 else out_msgs[0]
                        else:
                            output_val = {"role": "assistant", "content": str(output_val)} if output_val else output_val

                model = _pick(attrs, "gen_ai.request.model", "gen_ai.response.model", "llm.model_name")
                p_tok = int(_pick(attrs, "gen_ai.usage.prompt_tokens", "llm.token_count.prompt",
                                  "gen_ai.usage.input_tokens", "llm.input_tokens") or 0)
                c_tok = int(_pick(attrs, "gen_ai.usage.completion_tokens", "llm.token_count.completion",
                                  "gen_ai.usage.output_tokens", "llm.output_tokens") or 0)
                unknown_meta = {k: v for k, v in attrs.items()
                                if not k.startswith(("openinference.", "llm.token_count",
                                                     "llm.input_tokens", "llm.output_tokens", "input.", "output."))
                                and not (k.startswith("gen_ai.") and not k.startswith("gen_ai.system"))
                                and not k.startswith(("gen_ai.prompt.", "gen_ai.completion.", "gen_ai.usage."))}

                span_out = {
                    "id": str(_hex_to_uuid(sp.get("spanId"), pad=True)),
                    "parent_span_id": (str(_hex_to_uuid(sp["parentSpanId"], pad=True))
                                       if sp.get("parentSpanId") else None),
                    "name": sp.get("name")[:200],
                    "span_type": span_type_eff,
                    "model": model,
                    "status": "error" if is_error else "ok",
                    "error": err_text,
                    "input": input_val,
                    "output": output_val,
                    "metadata": {"otel.resource": system, **unknown_meta},
                    "prompt_tokens": p_tok,
                    "completion_tokens": c_tok,
                    "total_tokens": p_tok + c_tok,
                    "start_time": start,
                    "end_time": end,
                }
                if span_type == "llm":
                    span_out["cost"] = estimate_cost(model, p_tok, c_tok)
                trace["spans"].append(span_out)
                trace["start_time"] = min(x for x in [trace["start_time"], start] if x)
                trace["end_time"] = max(x for x in [trace["end_time"], end] if x)
                if is_error:
                    trace["status"] = "error"
                    trace["error"] = err_text

    out = []
    for tr in traces.values():
        # start_time / end_time 保持 datetime 对象（调用方直接计算 latency）
        tr["prompt_tokens"] = sum(s["prompt_tokens"] for s in tr["spans"])
        tr["completion_tokens"] = sum(s["completion_tokens"] for s in tr["spans"])
        tr["total_tokens"] = sum(s["total_tokens"] for s in tr["spans"])
        tr["cost"] = sum(s.get("cost", 0.0) for s in tr["spans"] if s["span_type"] == "llm")
        tr["input"] = next((s["input"] for s in tr["spans"] if not s["parent_span_id"]), None)
        tr["output"] = next((s["output"] for s in tr["spans"] if not s["parent_span_id"]), None)
        out.append(tr)
    return out


@router.post("/v1/traces", status_code=201)
def otel_traces(doc: dict, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    """OTLP/HTTP(JSON) 批量接入。"""
    payloads = convert_resource_spans(doc)
    if not payloads:
        raise HTTPException(status_code=422, detail="no resourceSpans found")
    created = []
    for p in payloads:
        trace = Trace(
            project_id=project.id,
            name=p["name"][:200],
            session_id=None,
            status=p["status"],
            error=p["error"],
            input=p["input"],
            output=p["output"],
            start_time=p["start_time"],
            end_time=p["end_time"],
            latency_ms=int((p["end_time"] - p["start_time"]).total_seconds() * 1000),
            prompt_tokens=p["prompt_tokens"],
            completion_tokens=p["completion_tokens"],
            total_tokens=p["total_tokens"],
            cost=p["cost"],
        )
        db.add(trace)
        db.flush()
        for s in p["spans"]:
            s_start, s_end = s["start_time"], s["end_time"]
            db.add(Span(
                id=uuid.UUID(s["id"]),
                trace_id=trace.id,
                parent_span_id=uuid.UUID(s["parent_span_id"]) if s["parent_span_id"] else None,
                name=s["name"], span_type=s["span_type"], model=s["model"],
                status=s["status"], error=s["error"],
                input=s["input"], output=s["output"], meta=s.get("metadata"),
                prompt_tokens=s["prompt_tokens"], completion_tokens=s["completion_tokens"],
                total_tokens=s["total_tokens"],
                cost=estimate_cost(s["model"], s["prompt_tokens"], s["completion_tokens"]) if s["span_type"] == "llm" else 0.0,
                start_time=s_start, end_time=s_end,
                latency_ms=int((s_end - s_start).total_seconds() * 1000),
            ))
        created.append(str(trace.id))
    db.commit()
    return {"count": len(created), "ids": created}
