"""最小 SDK 接入示例：先启动 LLMTrace 服务并创建项目拿到 API Key。"""
import os

from openai import OpenAI

from llmtrace import wrap_openai

client = wrap_openai(OpenAI())  # 读取 LLMTRACE_URL / LLMTRACE_API_KEY / LLMTRACE_PROJECT_ID

resp = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "用一句话介绍链路追踪"}],
)
print(resp.choices[0].message.content)
assert os.environ.get("LLMTRACE_API_KEY"), "请设置 LLMTRACE_API_KEY"
