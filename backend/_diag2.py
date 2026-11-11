import json, sys
sys.path.insert(0, '.')
from app.api.otel import convert_resource_spans
doc = {
    "resourceSpans": [{
        "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "w"}}]},
        "scopeSpans": [{"spans": [{
            "traceId": "4bf92f3577b34da6a3ce929d0e0e4736", "spanId": "00f067aa0ba902b8",
            "name": "chat", "kind": 3,
            "startTimeUnixNano": 1731216000100000000, "endTimeUnixNano": 1731216001400000000,
            "attributes": [
                {"key": "openinference.span.kind", "value": {"stringValue": "LLM"}},
                {"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4o-mini"}},
                {"key": "gen_ai.prompt.1.content", "value": {"stringValue": "长沙天气"}},
                {"key": "gen_ai.prompt.1.role", "value": {"stringValue": "user"}},
                {"key": "gen_ai.completion.1.content", "value": {"stringValue": "晴天"}},
                {"key": "gen_ai.completion.1.role", "value": {"stringValue": "assistant"}},
            ],
            "status": {"code": 1},
        }]}],
    }],
}
out = convert_resource_spans(doc)
print(json.dumps(out[0]["spans"][0], ensure_ascii=False, default=str, indent=1)[:900])
