"""llmtrace: minimal SDK for reporting LLM traces to an LLMTrace server."""

import atexit
import inspect
import json
import os
import queue
import re
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from functools import wraps

_config = {"api_url": None, "api_key": None, "project_id": None, "buffer_path": None}
_queue = queue.Queue()
_sender_started = False
_max_retries = 3
_buffer_lock = threading.Lock()

_current_trace = ContextVar("llmtrace_current_trace", default=None)

MASK_PATTERNS = {
    "phone": (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[phone]"),
    "email": (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email]"),
    "id_card": (re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"), "[id]"),
}
_mask_patterns = []


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _new_state(session_id=None):
    return {"trace_id": str(uuid.uuid4()), "session_id": session_id, "spans": [], "stack": []}


def _safe_repr(value):
    try:
        return repr(value)
    except Exception:
        return "<unrepresentable>"

def _jsonable(value):
    """Return value as-is when JSON-serializable, else a readable repr."""
    try:
        json.dumps(value)
        return value
    except Exception:
        return _safe_repr(value)


def _capture_input(args, kwargs):
    """Capture function input the way LangSmith would: a single positional
    argument is stored raw; multiple args / kwargs become structured dicts."""
    if kwargs:
        cap = {k: _jsonable(v) for k, v in kwargs.items()}
        if args:
            cap["args"] = [_jsonable(a) for a in args]
        return cap
    if len(args) == 1:
        return _jsonable(args[0])
    if args:
        return [_jsonable(a) for a in args]
    return None


def configure(api_url=None, api_key=None, project_id=None, masking=None, buffer=True, buffer_path=None):
    """Configure the SDK. Env vars: LLMTRACE_URL / LLMTRACE_API_KEY / LLMTRACE_PROJECT_ID.

    masking: True enables all built-in PII rules, or a list like ["phone", "email"].
    buffer:  failed payloads are persisted to disk and retried on next startup.
    buffer_path: override the buffer file location.
    """
    global _sender_started, _mask_patterns
    _config["api_url"] = api_url or os.getenv("LLMTRACE_URL", "http://localhost:8000")
    _config["api_key"] = api_key or os.getenv("LLMTRACE_API_KEY", "")
    _config["project_id"] = project_id or os.getenv("LLMTRACE_PROJECT_ID", "")
    _config["buffer_path"] = (
        None if buffer is False
        else buffer_path or os.getenv("LLMTRACE_BUFFER_PATH")
        or os.path.join(tempfile.gettempdir(), "llmtrace-buffer.jsonl")
    )
    if masking is True:
        keys = list(MASK_PATTERNS)
    elif isinstance(masking, (list, tuple)):
        keys = masking
    else:
        keys = []
    _mask_patterns = [MASK_PATTERNS[k] for k in keys if k in MASK_PATTERNS]
    if not _sender_started:
        threading.Thread(target=_sender_loop, daemon=True).start()
        _sender_started = True
        atexit.register(_drain, 2.0)


def _request(path, body):
    url = _config["api_url"].rstrip("/") + path
    headers = {"Content-Type": "application/json", "X-API-Key": _config["api_key"] or ""}
    if _config["project_id"]:
        headers["X-Project-Id"] = str(_config["project_id"])
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


def _buffer_save(batch):
    """Persist failed payloads to disk (JSON lines, 5MB cap) for later retry."""
    path = _config["buffer_path"]
    if not path:
        return
    with _buffer_lock, open(path, "a", encoding="utf-8") as f:
        for p in batch:
            f.write(json.dumps(p, default=str) + "\n")
    try:
        if os.path.getsize(path) > 5 * 1024 * 1024:
            with open(path, "r", encoding="utf-8") as f:
                tail = f.readlines()[-2000:]
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(tail)
    except OSError:
        pass


def _buffer_load():
    """Read and clear the disk buffer. Returns payloads from previous runs."""
    path = _config["buffer_path"]
    if not path or not os.path.exists(path):
        return []
    payloads = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                payloads.append(json.loads(line))
            except Exception:
                pass
    try:
        os.remove(path)
    except OSError:
        pass
    return payloads


def _post_batch(batch):
    body = json.dumps({"traces": batch}, default=str).encode("utf-8")
    _request("/api/v1/traces/ingest-batch", body)


def _send_with_retry(batch):
    for attempt in range(_max_retries):
        try:
            _post_batch(batch)
            return True
        except Exception:
            time.sleep(0.5 * (attempt + 1))
    _buffer_save(batch)
    return False


def _sender_loop():
    buffered = _buffer_load()
    if buffered:
        _send_with_retry(buffered)
    while True:
        batch = []
        try:
            batch.append(_queue.get(timeout=2.0))
        except queue.Empty:
            continue
        deadline = time.time() + 1.0
        while len(batch) < 50:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                batch.append(_queue.get(timeout=remaining))
            except queue.Empty:
                break
        _send_with_retry(batch)
        _queue.task_done()  # 配合 _queue.join()：发送完成（或落盘缓冲）后解除阻塞


def _drain(timeout=2.0):
    batch = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            batch.append(_queue.get_nowait())
        except queue.Empty:
            break
    if batch:
        _send_with_retry(batch)


def _apply_masks(obj):
    if not _mask_patterns:
        return obj
    if isinstance(obj, str):
        for pattern, replacement in _mask_patterns:
            obj = pattern.sub(replacement, obj)
        return obj
    if isinstance(obj, dict):
        return {k: _apply_masks(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_apply_masks(v) for v in obj]
    return obj


def _submit(state):
    roots = [s for s in state["spans"] if s["parent_span_id"] is None]
    root = roots[0] if roots else None
    payload = {
        "name": (root or {}).get("name", "trace"),
        "session_id": state.get("session_id"),
        "status": (root or {}).get("status", "ok"),
        "error": (root or {}).get("error"),
        "input": (root or {}).get("input"),
        "output": (root or {}).get("output"),
        "metadata": {"trace_id": state["trace_id"]},
        "start_time": (root or {}).get("start_time") or _now_iso(),
        "end_time": (root or {}).get("end_time") or _now_iso(),
        "spans": [
            {
                "id": s["id"],
                "parent_span_id": s["parent_span_id"],
                "name": s["name"],
                "span_type": s["span_type"],
                "model": s.get("model"),
                "status": s["status"],
                "error": s.get("error"),
                "input": s.get("input"),
                "output": s.get("output"),
                "metadata": s.get("metadata"),
                "prompt_tokens": s.get("prompt_tokens", 0),
                "completion_tokens": s.get("completion_tokens", 0),
                "total_tokens": s.get("total_tokens", 0),
                "start_time": s["start_time"],
                "end_time": s["end_time"],
            }
            for s in state["spans"]
        ],
    }
    _queue.put(_apply_masks(payload))


@contextmanager
def span(name, span_type="chain", *, input=None, model=None, metadata=None, session_id=None):
    """Record a span. Creates a new trace automatically at the outermost level."""
    state = _current_trace.get()
    is_root = state is None
    if state is None:
        state = _new_state(session_id=session_id)

    rec = {
        "id": str(uuid.uuid4()),
        "parent_span_id": state["stack"][-1] if state["stack"] else None,
        "name": name,
        "span_type": span_type,
        "model": model,
        "status": "ok",
        "error": None,
        "input": input,
        "output": None,
        "metadata": metadata,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    state["spans"].append(rec)
    state["stack"].append(rec["id"])
    token = _current_trace.set(state)
    t0 = time.perf_counter()
    start_iso = _now_iso()
    try:
        yield rec
    except BaseException as exc:
        rec["status"] = "error"
        rec["error"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        rec["start_time"] = start_iso
        rec["end_time"] = _now_iso()
        rec["latency_ms"] = round((time.perf_counter() - t0) * 1000)
        state["stack"].pop()
        _current_trace.reset(token)
        if is_root and not state["stack"]:
            if not _config["api_url"]:
                configure()
            _submit(state)


def trace(name=None, *, span_type="chain", session_id=None, metadata=None):
    """Decorator version of span() for sync AND async functions."""
    def deco(fn):
        if inspect.iscoroutinefunction(fn):
            @wraps(fn)
            async def async_wrapper(*args, **kwargs):
                with span(name or fn.__name__, span_type=span_type,
                          input=_capture_input(args, kwargs),
                          metadata=metadata, session_id=session_id) as rec:
                    result = await fn(*args, **kwargs)
                    rec["output"] = result
                    return result
            return async_wrapper

        @wraps(fn)
        def wrapper(*args, **kwargs):
            with span(name or fn.__name__, span_type=span_type,
                      input=_capture_input(args, kwargs),
                      metadata=metadata, session_id=session_id) as rec:
                result = fn(*args, **kwargs)
                rec["output"] = result
                return result
        return wrapper
    return deco


def record_llm_call(model, input=None, output=None, prompt_tokens=0,
                    completion_tokens=0, latency_ms=None, metadata=None, error=None):
    """Record a single LLM call as a span (type=llm) inside the current trace."""
    state = _current_trace.get()
    is_root = state is None
    if state is None:
        state = _new_state()
    start_dt = datetime.now(timezone.utc)
    end_dt = start_dt + timedelta(milliseconds=latency_ms or 0)
    rec = {
        "id": str(uuid.uuid4()),
        "parent_span_id": state["stack"][-1] if state["stack"] else None,
        "name": model or "llm-call",
        "span_type": "llm",
        "model": model,
        "status": "error" if error else "ok",
        "error": error,
        "input": input,
        "output": output,
        "metadata": metadata,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat(),
        "latency_ms": latency_ms or 0,
    }
    state["spans"].append(rec)
    if is_root:
        if not _config["api_url"]:
            configure()
        _submit(state)
