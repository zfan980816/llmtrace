"""SDK unit tests with a stub HTTP sender. Run: python test_sdk.py"""
import asyncio
import sys
import time

sys.path.insert(0, r"D:\LangSmithClone\sdk")

import llmtrace
from llmtrace import client as lc

lc._sender_started = True  # keep the background thread off; we drain the queue manually
llmtrace.configure(api_url="http://test", api_key="k", project_id="p")


def flush():
    out = []
    while not lc._queue.empty():
        out.append(lc._queue.get())
    return out


# 1. sync decorator + nested span + record_llm_call
@llmtrace.trace(name="job", session_id="s1")
def job():
    with llmtrace.span("inner", input={"x": 1}):
        time.sleep(0.01)
    llmtrace.record_llm_call(
        model="gpt-4o-mini",
        input=[{"role": "user", "content": "hi"}],
        output="yo",
        prompt_tokens=10, completion_tokens=5, latency_ms=7,
    )
    return "ok"


assert job() == "ok"
t = flush()[-1]
assert t["name"] == "job" and t["session_id"] == "s1" and t["status"] == "ok"
assert len(t["spans"]) == 3, t["spans"]
assert {s["span_type"] for s in t["spans"]} == {"chain", "llm"}
inner = [s for s in t["spans"] if s["name"] == "inner"][0]
assert inner["parent_span_id"] is not None
print("sync decorator: OK")

# 2. async decorator
@llmtrace.trace(name="ajob")
async def ajob():
    await asyncio.sleep(0.01)
    return 42


assert asyncio.run(ajob()) == 42
t = flush()[-1]
assert t["name"] == "ajob" and t["spans"][0]["status"] == "ok"
print("async decorator: OK")

# 3. error capture
@llmtrace.trace(name="boom")
def boom():
    raise ValueError("bad")


try:
    boom()
except ValueError:
    pass
t = flush()[-1]
assert t["status"] == "error" and "ValueError" in t["error"]
assert t["spans"][0]["status"] == "error"
print("error capture: OK")


# 4. openai wrapper (non-streaming, mocked client)
class FakeUsage:
    prompt_tokens = 11
    completion_tokens = 7


class FakeMessage:
    content = "hello there"


class FakeChoice:
    message = FakeMessage()


class FakeResponse:
    choices = [FakeChoice()]
    usage = FakeUsage()


class FakeCompletions:
    def create(self, **kwargs):
        return FakeResponse()


class FakeChat:
    completions = FakeCompletions()


class FakeOpenAI:
    chat = FakeChat()


fake = llmtrace.wrap_openai(FakeOpenAI())
resp = fake.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}])
assert resp.choices[0].message.content == "hello there"
t = flush()[-1]
s = [x for x in t["spans"] if x["span_type"] == "llm"][0]
assert s["model"] == "gpt-4o-mini" and s["prompt_tokens"] == 11 and s["completion_tokens"] == 7
assert s["output"] == "hello there"
assert s["end_time"] > s["start_time"]  # latency reflected in timestamps
print("openai wrapper: OK")


# 5. openai streaming wrapper
class FakeDelta:
    def __init__(self, text):
        self.content = text


class FakeChunk:
    def __init__(self, text):
        self.choices = [type("C", (), {"delta": FakeDelta(text)})()]


class FakeStream:
    def __iter__(self):
        for text in ["hel", "lo ", "world"]:
            yield FakeChunk(text)


class FakeStreamCompletions:
    def create(self, **kwargs):
        return FakeStream()


class FakeChat2:
    completions = FakeStreamCompletions()


class FakeOpenAI2:
    chat = FakeChat2()


fake2 = llmtrace.wrap_openai(FakeOpenAI2())
parts = [
    c.choices[0].delta.content
    for c in fake2.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": "hi"}], stream=True
    )
]
assert parts == ["hel", "lo ", "world"]
t = flush()[-1]
s = [x for x in t["spans"] if x["span_type"] == "llm"][0]
assert s["output"] == "hello world", s["output"]
print("openai stream wrapper: OK")


# 6. anthropic wrapper (non-streaming, mocked client)
class AFakeUsage:
    input_tokens = 20
    output_tokens = 30


class ABlock:
    text = "bonjour"


class AResponse:
    content = [ABlock()]
    usage = AFakeUsage()


class AFakeMessages:
    def create(self, **kwargs):
        return AResponse()


class AFakeClient:
    messages = AFakeMessages()


ac = llmtrace.wrap_anthropic(AFakeClient())
ac.messages.create(model="claude-3-5-haiku", messages=[{"role": "user", "content": "salut"}])
t = flush()[-1]
s = [x for x in t["spans"] if x["span_type"] == "llm"][0]
assert s["model"] == "claude-3-5-haiku" and s["prompt_tokens"] == 20 and s["completion_tokens"] == 30
assert s["output"] == "bonjour"
print("anthropic wrapper: OK")

print("")
print("ALL SDK TESTS PASSED")




