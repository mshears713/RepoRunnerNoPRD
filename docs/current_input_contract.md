# Current Input Contract — Repo Viability Scanner

> **Purpose:** Reverse-engineered contract of the existing system's input schema.  
> **Audience:** Engineers preparing a schema migration.  
> **Rule:** Where documentation and code disagree, this document trusts the code.

---

## 1. Input Schema Overview

### 1.1 Current Schema

```json
{
  "repo_url": "string (required)",
  "summary": "string | null (optional)",
  "reason_selected": "string | null (optional)",
  "tags": ["string"] | null (optional)",
  "priority": "string | null (optional)"
}
```

### 1.2 Pydantic Model (source of truth)

**File:** `backend/routes/scan.py:28–46`

```python
class ScanRequest(BaseModel):
    repo_url: str
    summary: str | None = None
    reason_selected: str | None = None
    tags: list[str] | None = None
    priority: str | None = None

    @field_validator("repo_url")
    @classmethod
    def validate_github_url(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("repo_url must be an http/https URL")
        if "github.com" not in parsed.netloc:
            raise ValueError("repo_url must be a github.com URL")
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 2 or not parts[1]:
            raise ValueError("repo_url must include owner and repo name")
        return v.rstrip("/")
```

### 1.3 Ingestion Point

| Property | Value |
|----------|-------|
| **File** | `backend/routes/scan.py` |
| **Endpoint** | `POST /api/scan` |
| **Function** | `submit_scan(body: ScanRequest, background_tasks: BackgroundTasks)` |
| **Line** | 120 |
| **Validation** | Pydantic (FastAPI auto-parses + validates request body) |

---

## 2. Field-by-Field Analysis

### 2.1 `repo_url`

**Type:** `str` — **REQUIRED**  
**Importance:** CRITICAL

**Validation** (`scan.py:35–46`):
- Must use `http` or `https` scheme
- Must contain `github.com` in the netloc
- Must have `owner` and `repo` path components
- Trailing slashes are stripped

**Usage map:**

| File | Line(s) | How Used |
|------|---------|----------|
| `routes/scan.py` | 71–73 | `_parse_github_url()` splits path into `(owner, repo)` tuple |
| `routes/scan.py` | 122 | `owner, repo = _parse_github_url(body.repo_url)` at request time |
| `routes/scan.py` | 128 | Dedup check compares extracted `owner`/`repo` against recent scans |
| `routes/scan.py` | 142 | Stored directly on scan document: `"repo_url": body.repo_url` |
| `routes/scan.py` | 143–144 | Decomposed into `"repo_owner"` and `"repo_name"` on scan doc |
| `routes/scan.py` | 225, 239 | Retrieved from source scan and reused for reruns |
| `pipeline.py` | 143–156 | `scan['repo_owner']` / `scan['repo_name']` used to fork repo via GitHub API |

**Effect on execution:** Direct and decisive. Without a valid `repo_url`, no scan can proceed. The extracted `owner/repo` pair drives every GitHub API call in the pipeline.

---

### 2.2 `summary`

**Type:** `str | None` — **OPTIONAL**  
**Importance:** USEFUL (context enrichment only)

**Usage map:**

| File | Line(s) | How Used |
|------|---------|----------|
| `routes/scan.py` | 146 | Stored in `input_metadata.summary` on scan document |
| `routes/scan.py` | 241 | Preserved across reruns via `source.get("input_metadata", {})` |
| `result_analyzer.py` | 26 | Retrieved as part of `upstream = scan.get("input_metadata", {})` |
| `gemini_analyzer.py` | 51–54 | Serialized into `upstream_str` and injected into the AI summary prompt |

**Effect on execution:** None. Does not affect forking, Codespace creation, running, or port detection. It influences only the Gemini-generated `analysis.what_it_does` / `analysis.use_case` text in the final result.

**Note on serialization:** `upstream_str` is built as `"\n".join(f"{k}: {v}" for k, v in upstream_metadata.items() if v)`. A `None` value is filtered out by the `if v` check. An empty string `""` is also filtered out.

---

### 2.3 `reason_selected`

**Type:** `str | None` — **OPTIONAL**  
**Importance:** USEFUL (context enrichment only)

**Usage map:**

| File | Line(s) | How Used |
|------|---------|----------|
| `routes/scan.py` | 147 | Stored in `input_metadata.reason_selected` on scan document |
| `routes/scan.py` | 241 | Preserved across reruns via `source.get("input_metadata", {})` |
| `result_analyzer.py` | 26 | Retrieved as part of `upstream = scan.get("input_metadata", {})` |
| `gemini_analyzer.py` | 51–54 | Serialized into `upstream_str` and injected into the AI summary prompt |

**Effect on execution:** None. Same path as `summary` — stored, preserved, passed to AI. Does not branch execution logic or affect scoring.

---

### 2.4 `tags`

**Type:** `list[str] | None` — **OPTIONAL**  
**Importance:** USEFUL (context enrichment only)

**Usage map:**

| File | Line(s) | How Used |
|------|---------|----------|
| `routes/scan.py` | 148 | Stored as `input_metadata.tags`; `None` is normalized to `[]` via `body.tags or []` |
| `routes/scan.py` | 241 | Preserved across reruns via `source.get("input_metadata", {})` |
| `result_analyzer.py` | 26 | Retrieved as part of `upstream = scan.get("input_metadata", {})` |
| `gemini_analyzer.py` | 51–54 | Serialized into `upstream_str` and injected into the AI summary prompt |

**Effect on execution:** None. Despite being a list type, tags are never iterated over for execution branching. They are only stringified and passed to the AI.

**Note on normalization:** `body.tags or []` means `None` becomes `[]` at storage time. The stored value is always a list (possibly empty), unlike the other nullable fields.

---

### 2.5 `priority`

**Type:** `str | None` — **OPTIONAL**  
**Importance:** UNUSED for execution; cosmetic

**Usage map:**

| File | Line(s) | How Used |
|------|---------|----------|
| `routes/scan.py` | 149 | Stored as `input_metadata.priority` on scan document |
| `routes/scan.py` | 241 | Preserved across reruns via `source.get("input_metadata", {})` |
| `result_analyzer.py` | 26 | Retrieved as part of `upstream = scan.get("input_metadata", {})` |
| `gemini_analyzer.py` | 51–54 | Serialized into `upstream_str` and injected into the AI summary prompt |

**Effect on execution:** None. There is no queue prioritization, scheduling, or resource allocation based on this field. It is not validated against an enum. Any string value (or `null`) is accepted and stored as-is.

---

## 3. Execution Flow

```
POST /api/scan  { repo_url, summary, reason_selected, tags, priority }
│
├─ [ScanRequest Pydantic validation]
│    repo_url → validated (scheme, domain, owner/repo path) ← ONLY field validated
│    summary, reason_selected, tags, priority → accepted as-is (no validation)
│
├─ submit_scan()  [routes/scan.py:120]
│    ├─ Parse repo_url → (owner, repo)
│    ├─ Dedup check: owner+repo within last 24 hours? → 409 if yes
│    ├─ Create scan document:
│    │    repo_url, repo_owner, repo_name     ← from repo_url
│    │    input_metadata: {                   ← from remaining 4 fields
│    │      summary, reason_selected,
│    │      tags (normalized to []),
│    │      priority
│    │    }
│    │    status: "queued"
│    ├─ Persist to /data/scans/{scan_id}.json
│    ├─ Queue background task: _run_pipeline(scan_id)
│    └─ Return { id, status: "queued" }
│
│    [input_metadata fields are now dormant — no further read until Stage 4]
│
└─ ScanPipeline.run(scan_id)  [pipeline.py:96]  [background thread]
     │
     ├─ STAGE 1: Fork  [pipeline.py:142]
     │    Uses: scan['repo_owner'], scan['repo_name']  ← derived from repo_url
     │    Actions:
     │      - github_client.fork_repo(owner, repo, scan_id)
     │      - Wait for fork ready
     │      - fork_preparer.prepare_fork(): commit devcontainer.json + run.sh to fork
     │    Stores: fork_repo_name on scan doc
     │
     ├─ STAGE 2: Codespace  [pipeline.py:225]
     │    Uses: scan['fork_repo_name']
     │    Actions:
     │      - codespaces_client.create_codespace(fork_name)
     │      - devcontainer.json triggers: postStartCommand = "bash run.sh"
     │      - Poll until codespace state = "Available"
     │    Stores: codespace_name on scan doc
     │
     ├─ STAGE 3: Execute  [pipeline.py:256]
     │    Uses: fork_repo_name, codespace_name
     │    run.sh logic (assets/run.sh):
     │      ├─ if package.json exists → npm install → npm start (port 3000)
     │      ├─ elif requirements.txt exists → pip install -r requirements.txt
     │      │    ├─ if main.py exists → python3 main.py (port 8000)
     │      │    └─ elif app.py exists → python3 app.py (port 8000)
     │      └─ else → write failure result (exit_code=1)
     │    Port detection: nc/lsof on expected port → parse stdout → no port (non-server)
     │    Result written to: scanner_result.json → git push to fork
     │    result_fetcher polls: fork's scanner_result.json via GitHub API (max 180s)
     │    Fallback: HTTP probe on ports [8000, 3000, 8080, 5000]
     │    Stores: execution dict on scan doc
     │
     └─ STAGE 4: Analyze  [pipeline.py: _stage_analyze]
          Uses: input_metadata  ← FIRST time summary/reason_selected/tags/priority are read
          Actions:
            - github_client.get_repo_metadata() → description, language, topics, readme
            - github_client.get_file_tree() → top 80 files
            - result_analyzer.analyze(scan, repo_metadata, file_tree)
                └─ gemini_analyzer.summarize(
                     repo_full_name, description, language, topics,
                     readme_excerpt, execution,
                     upstream_metadata=scan['input_metadata']  ← all 4 optional fields
                   )
                   → { what_it_does, use_case, tech_stack, caveats }
            - if not started: gemini_analyzer.diagnose_failure(...)
                   → { category, plain_explanation, fix_suggestions }
                   Note: input_metadata is NOT passed to diagnose_failure
            - Schedule cleanup: codespace_expires_at = now + ttl_seconds
          Stores: analysis, failure, codespace_expires_at on scan doc
```

---

## 4. Assumptions & Limitations

### 4.1 Hardcoded Project Type Detection (`assets/run.sh`)

The entire execution strategy is determined by a fixed cascade in `run.sh`. The input schema has **no influence** on this logic.

| Assumption | File | Line | Detail |
|-----------|------|------|--------|
| Node project = `package.json` present | `run.sh` | 119 | No other Node indicators checked |
| Node always starts with `npm start` | `run.sh` | 124 | No `npm run dev`, yarn, pnpm, bun |
| Node default port = 3000 | `run.sh` | 123 | Hardcoded; dynamic detection is a fallback |
| Python project = `requirements.txt` present | `run.sh` | 141 | No `pyproject.toml`, `setup.py`, `Pipfile` |
| Python entry point = `main.py` or `app.py` only | `run.sh` | 155, 170 | No `server.py`, `run.py`, `wsgi.py`, etc. |
| Python default port = 8000 | `run.sh` | 154 | Hardcoded; dynamic detection is a fallback |
| No package.json + no main.py/app.py = failure | `run.sh` | 187–191 | Even valid repos fail if they don't match pattern |
| Port detection timeout = 60 seconds | `run.sh` | 63 | `wait_for_port` max_wait hardcoded |

### 4.2 Infrastructure Assumptions

| Assumption | File | Line | Detail |
|-----------|------|------|--------|
| All repos are on GitHub (not GitLab, Bitbucket) | `scan.py` | 41 | Validator rejects non-github.com URLs |
| Codespace machine = `basicLinux32gb` | `codespaces_client.py` | 31 | Hardcoded; no schema input to change it |
| Execution timeout = 180 seconds | `config.py` | 37 | `result_fetcher` gives up after this |
| Fork poll timeout = 120 seconds | `config.py` | 23 | Fork readiness wait ceiling |
| Codespace ready timeout = 300 seconds | `config.py` | ~30 | Codespace creation poll ceiling |
| Fallback HTTP probe ports = [8000, 3000, 8080, 5000] | `result_fetcher.py` | 49 | Order is fixed |
| Dedup window = 24 hours | `scan.py` | 126 | Same repo resubmitted within 24h → 409 |
| AI model = `gemini-2.0-flash` | `gemini_analyzer.py` | 28 | Hardcoded |
| Result file = `scanner_result.json` | `result_fetcher.py` | 19 | Hardcoded filename expected in fork root |

### 4.3 Implicit Web-App Bias

The system's `run.sh` is designed for repos that start a server and listen on a port. Repos that are:
- Libraries / packages
- CLI tools
- Data pipelines
- Static site generators
- Anything requiring environment variables

...will either silently "succeed" with `stage_reached=completed` (no port found but no crash) or hard-fail. There is no distinction between these outcomes in the schema or the execution logic.

---

## 5. Dead / Removable Fields

### Fields with no execution effect

| Field | Assessment | Reasoning |
|-------|-----------|-----------|
| `summary` | **Removable without breaking execution** | Only appears in AI prompt. Removing it omits context from the Gemini summary but execution is unaffected. |
| `reason_selected` | **Removable without breaking execution** | Same path as `summary`. Purely cosmetic for AI context. |
| `tags` | **Removable without breaking execution** | Never iterated, never used in conditionals. Passed raw to AI prompt as a stringified list. |
| `priority` | **Removable without breaking execution** | No queue, no scheduler, no prioritization logic exists. Accepted, stored, forwarded to AI, ignored otherwise. |

### Fields that cannot be removed

| Field | Assessment | Reasoning |
|-------|-----------|-----------|
| `repo_url` | **Critical — cannot be removed** | The entire pipeline depends on `repo_owner` and `repo_name` extracted from it. |

---

## 6. Migration Risk Areas

### 6.1 Tight Coupling Points

| Coupling | File | Risk |
|---------|------|------|
| `repo_url` validation is GitHub-specific | `scan.py:35–46` | Adding support for non-GitHub repos requires new validator logic and all downstream API clients |
| `input_metadata` dict structure is free-form | `scan.py:145–150` | Any new schema fields must be added here or the storage contract changes |
| `input_metadata` is passed wholesale to AI | `result_analyzer.py:26`, `gemini_analyzer.py:51–54` | New fields will automatically appear in the AI prompt — this may or may not be desired |
| `run.sh` is a static bash script committed to every fork | `fork_preparer.py`, `pipeline.py:170` | Execution strategy cannot be dynamic without replacing or parameterizing `run.sh` |

### 6.2 What the Proposed Schema Adds That Will Break Things

The `repo_viability_schema_handoff.md` proposes fields like `execution_category`, `execution_profile`, `execution.install`, `execution.run`, `execution.mode`, `port.expected`, `validation.smoke_tests`, etc.

**None of these are wired up.** Adding them to the `ScanRequest` model without also modifying `run.sh`, `pipeline.py`, and `result_fetcher.py` will result in silently ignored fields.

Specific break points when migrating to the new schema:

| Risk | Details |
|------|---------|
| `run.sh` must become dynamic | Currently hardcoded. If `execution.run` commands come from the schema, `run.sh` must be templated or replaced |
| Port strategy must be honored | `port.expected` in new schema must override the hardcoded `PORT=3000` / `PORT=8000` in `run.sh` |
| `execution_category` has no current routing | No code branches on category. Adding it to input without routing logic means it does nothing |
| `validation.smoke_tests` has no runner | No test runner exists in `run.sh` or `pipeline.py` |
| `input_metadata` key must be preserved or migrated | Rerun logic at `scan.py:241` reads `source.get("input_metadata", {})` — renaming this key breaks reruns |
| Old scans on disk use old schema | `/data/scans/*.json` files use the current structure. Any reader must be backward-compatible |

### 6.3 Safe Migration Path

1. **`summary`, `reason_selected`, `tags`, `priority`** can be removed or replaced freely — no execution depends on them.
2. **`repo_url`** must remain or be mapped directly — it is the only field that drives real work.
3. **New execution-directive fields** (`execution`, `port`, `validation`) require corresponding changes in `run.sh` and `pipeline.py` to have any effect.
4. **The `input_metadata` storage key** in scan documents is the one structural coupling point across storage, reruns, and AI analysis.
