# Release Checklist & Notes

## v0.1.0 — first public release (draft)

### Highlights

- **Full-trace observability** for LLM apps: traces → spans (llm / tool / retrieval / agent / chain)
  with complete inputs, outputs, tool calls, tokens, cost and latency
- **LangSmith-style UI**: Threads / Traces / Runs views, collapsible span tree with
  latency/tokens/model badges, chat-bubble message rendering with Markdown,
  structured tool-call cards, light & dark themes (light default), 中文 / English toggle
- **Full-text search** across names, inputs, outputs and errors
- **Error clustering** on the dashboard with deep-links into filtered trace search
- **Feedback** — 👍/👎 with comments on any trace, RBAC-aware
- **Alerting** — threshold rules (error rate / latency), webhooks (JSON / Feishu / DingTalk / WeCom)
  with HMAC signatures and cooldown
- **Auth & SSO** — password login (with rate limiting), Feishu SSO, generic OIDC, GitHub OAuth;
  admin / member / viewer RBAC
- **Python SDK** — `wrap_openai` / `wrap_anthropic` (streaming), `@trace`/`@span` decorators,
  batch upload with disk buffer, PII masking
- **Ops-ready** — Alembic migrations, per-project data retention, CSV/JSON export,
  audit logs, demo seeding, one-command Docker deploy

- **OpenTelemetry ingestion** — OTLP/HTTP(JSON) endpoint with GenAI & OpenInference conventions

### Known limitations

- Dashboard / trace-detail pages are Chinese-first; nav & list pages are bilingual (i18n infra ready)
- Single-node deployment (WebSocket broadcast is in-process)

---

## Release checklist (every release)

1. **Version bump** — backend `app/config.py` or version file, `sdk/pyproject.toml`, this file
2. **Changelog** — update the notes below (user-facing changes only)
3. **Migrations** — `alembic revision --autogenerate -m "..."` for any model change;
   verify `alembic upgrade head` on an empty DB **and** on a copy of a production DB
4. **Tests green** — `backend`: smoke / auth / alerts / sessions / v05 / v06 / v07 / sso / feedback / ws;
   `sdk`: test_sdk.py; `frontend`: `npm run build` (CI runs all of this)
5. **Security pass** — no new default secrets; `.env.example` matches all new settings
6. **Docker** — `docker compose up -d --build` from a clean clone; verify migration + seed + login
7. **Docs** — README quickstart still accurate; screenshots refreshed if UI changed
8. **Tag & publish** — `git tag vX.Y.Z && git push --tags`; GitHub release with the notes below;
   `cd sdk && python -m build && twine upload dist/*` if SDK changed

---

## v0.1.0 go-live checklist (one-time)

- [ ] Create GitHub repo, push main branch
- [ ] Repo settings: description, topics (`llm`, `observability`, `langsmith-alternative`, `self-hosted`, `openai`, `tracing`), Apache-2.0 license detected
- [ ] Enable GitHub Actions (CI runs on push)
- [ ] Add repo social preview image (use `docs/screenshots/traces.png`)
- [ ] Verify README images render (relative `docs/screenshots/...` paths)
- [ ] Publish SDK to PyPI: `cd sdk && python -m build && twine upload dist/*`
- [ ] Write launch post: "Self-hosted LangSmith alternative in one container" (Show HN / V2EX / r/LocalLLaMA)
- [ ] Create Discussions tab + issue templates
- [ ] Announce: demo GIF in post = `docs/screenshots/walkthrough.gif`
