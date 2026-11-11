"""llmtrace demo - send a sample trace so you can see the UI working."""
import argparse
import os
import sys
import time
import uuid

from .client import configure, span


def main():
    parser = argparse.ArgumentParser(prog="llmtrace", description="LLMTrace SDK CLI")
    sub = parser.add_subparsers(dest="command")
    demo = sub.add_parser("demo", help="send a sample trace so you can see the dashboard with data")
    demo.add_argument("--url", default=os.environ.get("LLMTRACE_URL", "http://localhost:8000"))
    demo.add_argument("--key", default=os.environ.get("LLMTRACE_API_KEY", ""))
    demo.add_argument("--project", default=os.environ.get("LLMTRACE_PROJECT_ID", "default"))
    args = parser.parse_args()

    if args.command != "demo":
        parser.print_help()
        sys.exit(1)

    configure(api_url=args.url, api_key=args.key, project_id=args.project)
    sid = "demo-" + uuid.uuid4().hex[:8]

    with span(name="demo.conversation", span_type="chain", session_id=sid,
              input={"query": "what is llmtrace?"}) as root:
        with span(name="retrieve_context", span_type="retrieval",
                  input={"query": "what is llmtrace?"}) as sp:
            time.sleep(0.06)
            sp["output"] = {"documents": [
                "LLMTrace is a self-hosted LLM observability platform, Apache-2.0.",
                "Single Docker container, SQLite for trials, Postgres for production.",
            ]}
            sp["metadata"] = {"source": "llmtrace-demo"}
        with span(name="chat.completion", span_type="llm", model="gpt-4o-mini",
                  input={"messages": [
                      {"role": "system", "content": "You are a helpful assistant."},
                      {"role": "user", "content": "what is llmtrace?"},
                  ]}) as sp:
            time.sleep(0.12)
            sp["output"] = {"role": "assistant",
                            "content": "LLMTrace is a self-hosted LLM observability platform, similar to LangSmith but keeps data on your own server."}
            sp["prompt_tokens"] = 18
            sp["completion_tokens"] = 24
            sp["total_tokens"] = 42
            sp["metadata"] = {"cost_usd": 0.000042, "finish_reason": "stop"}

    import urllib.request
    try:
        urllib.request.urlopen(args.url.rstrip("/") + "/api/health", timeout=3)
    except Exception:
        print(f"warning: could not reach {args.url} - trace is queued and will retry")
    print(f"trace sent: {args.url}")
    print(f"session id: {sid}")
    print(f"open {args.url}/sessions and look for {sid}")


if __name__ == "__main__":
    main()
