"""为本地服务灌入演示数据（走 SDK 上报）。先启动服务并设置环境变量：
LLMTRACE_URL / LLMTRACE_API_KEY / LLMTRACE_PROJECT_ID
"""
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sdk"))

from llmtrace import configure, record_llm_call, span, trace

configure(
    api_url=os.environ.get("LLMTRACE_URL", "http://localhost:8000"),
    api_key=os.environ["LLMTRACE_API_KEY"],
    project_id=os.environ["LLMTRACE_PROJECT_ID"],
)

QUESTIONS = ["什么是 RAG？", "帮我总结这篇文章", "把这句话翻译成英文", "解释一下 token", "写一首关于秋天的诗"]
MODELS = ["gpt-4o-mini", "gpt-4o", "claude-3-5-haiku"]

for i, q in enumerate(QUESTIONS):
    session = "user-" + str(100 + i % 3)
    should_fail = i == 3

    @trace(name="rag-chat", session_id=session)
    def answer(question=q):
        with span("retrieve", span_type="retrieval", input={"question": question}):
            time.sleep(0.03)
        if should_fail:
            raise RuntimeError("LLM provider timeout after 30s")
        time.sleep(0.05 + random.random() * 0.15)
        model = MODELS[i % len(MODELS)]
        record_llm_call(
            model=model,
            input=[{"role": "system", "content": "You are a helpful assistant."},
                   {"role": "user", "content": question}],
            output={"role": "assistant", "content": "Answer for: " + question},
            prompt_tokens=random.randint(80, 300),
            completion_tokens=random.randint(40, 200),
        )
        return "ok"

    answer()
print("seed done")
