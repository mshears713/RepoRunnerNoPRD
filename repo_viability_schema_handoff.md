# Repo Viability Scanner — Schema Design Handoff

## Purpose of this document

This document captures the schema discussions, design rationale, execution categories, confidence model, and validation philosophy for the **orchestration-agent-generated execution plan** used by the Repo Viability Scanner.

This is intended as a **handoff document for the next build stage**. It is not the PRD for the whole product. It is specifically about the **schema layer** that sits between:

- the **orchestration/discovery agent** (Sauna OS / upstream intelligence)
- and the **RepoRunner execution system** (fork → Codespaces → run → validate → report)

The goal is to preserve not just the current schema direction, but the **reasoning behind it**, so future implementation decisions remain aligned with the system’s actual purpose.

---

# 1. System context

The Repo Viability Scanner is not a generic dev environment and not a broad recommendation engine.

Its role is:

- receive a repository that has already been pre-filtered by an upstream orchestration system
- determine what kind of execution value the repo can provide
- turn that into a structured plan
- run the repo in a sandbox (GitHub Codespaces)
- validate the outcome
- report a useful result back to the user

The upstream orchestration layer is responsible for:
- discovery
- relevance filtering
- high-level repo selection

The Repo Viability Scanner is responsible for:
- execution planning
- sandbox execution
- validation
- observability
- preview/result reporting

This means the schema is the **contract** between intelligence and execution.

---

# 2. Core design shift

Earlier thinking centered around a simple question:

> "Can this repo run?"

That turned out to be too blunt and too lossy.

The better question is:

> "What kind of value will I get if I run this repo, and how should the system treat it?"

This is the key shift.

A repo does not need to produce a webpage to be useful.
A repo does not need to be directly runnable to still be worth processing.
A library/framework can still be a successful outcome if the system correctly identifies it as installable + testable rather than attempting to launch it as an app.

So the schema should not model only "runnable vs not runnable."

It should model:

- the **execution category**
- the **expected behavior**
- the **appropriate validation strategy**
- the **confidence in each part of the plan**

---

# 3. Why the orchestration agent should generate the schema

A key architectural decision was made:

The LLM that inspects the repo should **not live inside the execution pipeline**.

Instead:

- the orchestration agent inspects the repo beforehand
- it reads the README, config files, scripts, and structure
- it outputs a structured JSON execution plan
- the execution pipeline then behaves deterministically from that plan

This is important because it gives:

- better separation of concerns
- cheaper execution runs
- less fragility at runtime
- easier debugging
- reusable intelligence
- a clean contract for future retries and fallbacks

The execution system should not be "thinking" while it is trying to run code.
It should be **executing a plan**.

---

# 4. What the schema is supposed to do

The schema is not just a list of commands.

It needs to describe:

1. **What kind of repo this is**
2. **What kind of execution experience is expected**
3. **Whether it should be run as a server, CLI, framework, etc.**
4. **How it should be installed**
5. **How it should be run, if it should be run**
6. **What validation/smoke tests should confirm success**
7. **How confident the agent is in each part of the plan**
8. **What caveats or constraints matter**

The schema therefore needs to be expressive enough to guide execution behavior, but simple enough for the orchestration agent to classify consistently.

---

# 5. Execution categories

A major improvement was replacing the simplistic "runnable / not runnable" concept with more useful execution categories.

These categories reflect the **user experience and execution strategy**, not just whether the repo technically starts.

## 5.1 `instant_ui`

Meaning:
- launches a visible web UI or page quickly
- highest immediate value to the user

Examples:
- React apps
- dashboards
- simple Flask/FastAPI frontends

Why it matters:
- these are the highest-signal repos for quick evaluation
- the runner should prioritize getting a preview URL

Expected behavior:
- long-running
- opens a port
- best validated by page/port availability

---

## 5.2 `service_api`

Meaning:
- runs as a backend service or API
- may not have a visible UI
- still useful because it exposes endpoints

Examples:
- FastAPI services
- Express APIs
- background microservices

Why it matters:
- useful even without a UI
- validation should emphasize port and endpoint health

Expected behavior:
- long-running
- opens a port
- validated via health checks, docs, or basic endpoint response

---

## 5.3 `cli_tool`

Meaning:
- runs as a command-line tool
- produces output and exits
- no long-lived process expected

Examples:
- generators
- migration tools
- script-based utilities

Why it matters:
- these should not be treated like servers
- validation should focus on exit code and output

Expected behavior:
- not long-running
- does not open a port
- validated via command success and expected stdout

---

## 5.4 `interactive_setup`

Meaning:
- can launch or partially run, but requires additional user action or configuration to be meaningfully used

Examples:
- auth-driven apps
- setup wizards
- tools needing API keys or connected services

Why it matters:
- these are not failures
- they should be surfaced differently from instant wins

Expected behavior:
- may open a port or may not
- often requires env vars or manual setup
- should be clearly flagged as partially ready

---

## 5.5 `dev_framework`

Meaning:
- a library, SDK, or framework intended to be imported or used as a building block
- not meant to be launched directly as a standalone app

Examples:
- FastMCP
- SDK repos
- internal frameworks

Why it matters:
- this was a major schema insight
- these repos are not "bad" or "red"
- they should be handled as install + validate rather than app run

Expected behavior:
- not long-running
- does not open a port
- validation should focus on install success, imports, CLI smoke tests, or basic object construction

---

## 5.6 `non_viable`

Meaning:
- not realistically executable in the RepoRunner sandbox
- or execution would not produce meaningful value within this system

Examples:
- broken repos
- infra requiring many external services
- GPU/cluster-dependent repos
- repos that only make sense as part of another system

Why it matters:
- this is the true "red"
- should be skipped or flagged rather than wasting compute

Expected behavior:
- no execution
- no smoke tests unless there is some minimal install-only validation worth doing

---

# 6. Why these categories are better

These categories allow the system to decide:

- whether to create a preview URL
- whether to run a long-lived process
- whether to run a one-shot CLI command
- whether to skip running and do install/validation only
- whether to avoid spending resources entirely

This is much better than a binary model because it preserves useful distinctions like:

- "web app"
- "API"
- "CLI"
- "framework"
- "requires setup"
- "not worth sandboxing"

This helps the product feel intelligent rather than brittle.

---

# 7. Execution profiles

A further refinement is that execution categories alone may not fully determine runtime behavior.

A useful additional field is an **execution profile**.

Examples:

- `full_run`
- `install_validate`
- `smoke_only`
- `skip_execution`

This allows the system to distinguish between:

- a repo that should be installed and run normally
- a framework that should only be installed and validated
- a repo that should only run smoke tests
- a repo that should be skipped entirely

### Example:
A `dev_framework` like FastMCP should typically use:

- `execution_category = "dev_framework"`
- `execution_profile = "install_validate"`

That tells the runner:

- install dependencies
- do not try to launch a server
- execute smoke tests
- report success if validation passes

This is more useful than pretending a framework repo is a failure.

---

# 8. Execution field philosophy

The `execution` block should remain straightforward and executable.

It should include:

- `install`: ordered list of install commands
- `run`: ordered list of primary run commands
- `mode`: one of:
  - `background`
  - `blocking`
  - `none`

## 8.1 Mode semantics

### `background`
Use when:
- a long-running server is expected
- the process needs to stay alive while the system probes ports or exposes a preview URL

Examples:
- `npm start`
- `uvicorn main:app`

### `blocking`
Use when:
- a one-shot command is intended
- the program runs, prints output, and exits

Examples:
- CLI tool
- generator
- migration command

### `none`
Use when:
- there is no meaningful run step
- repo should not be launched directly

Examples:
- frameworks/libraries
- install-only repos

This field matters because the runner should not infer process behavior from commands alone.

---

# 9. Port strategy

Ports should not be overspecified.

The earlier idea of always setting a guessed port was too fragile.

## Recommended design

If a server likely opens a port:

```json
"port": {
  "expected": 3000,
  "strategy": "detect"
}
```

or

```json
"port": {
  "expected": 8000,
  "strategy": "detect"
}
```

Why:
- expected port is still useful as a hint
- but dynamic detection is safer than trusting the guess

If the repo is not expected to open a port:

```json
"port": null
```

or, if an object form is preferred:

```json
"port": {
  "expected": null,
  "strategy": "none"
}
```

The important idea is:
- `detect` for likely servers
- `none` when ports are irrelevant

---

# 10. Environment requirements

The schema should include:

- `env.required`
- `env.optional`

This exists to capture:
- API keys
- auth secrets
- configuration variables
- optional tuning values like `PORT`

This matters because many repos appear runnable but are effectively blocked by missing environment setup.

The orchestration agent should:
- identify variables only when there is evidence
- not hallucinate env needs
- leave these arrays empty when unclear

This helps the runner avoid wasting Codespaces on impossible runs.

---

# 11. Validation and smoke tests

This became one of the most important schema improvements.

Earlier, fallback commands were doing double duty as ad hoc validation.
That was too implicit.

Smoke tests should be **first-class**.

## Why smoke tests matter

They provide:
- observable validation
- explicit success criteria
- reusable runner behavior
- meaningful success cases for frameworks and CLIs

Smoke tests allow the system to prove value even when there is no preview URL.

### Examples:
- CLI help command
- import check
- object construction
- health endpoint curl
- version check

---

## Recommended smoke test structure

Each smoke test should include:

- `name`
- `command`
- `success_criteria`
  - `exit_code`
  - optional `stdout_contains`
- `confidence`

Optional future improvement:
- `order`

### Why order may help
For some repos, there is a natural validation progression:

1. import test
2. CLI test
3. API/object test

This helps the runner produce more interpretable results and stop early when basic tests fail.

---

## What smoke tests should look like

They should be:
- minimal
- realistic
- fast
- aligned with repo type

For example, for a framework:
- import works
- CLI responds
- basic object can be constructed

For a service:
- install succeeds
- server starts
- port answers
- endpoint responds

For a CLI:
- `--help` works
- basic invocation returns expected output

---

# 12. Confidence model

Another important realization was that confidence should not be a single vague number.

The system needs **confidence by dimension**.

## Recommended breakdown

```json
"confidence": {
  "classification": number,
  "install": number,
  "run": number,
  "validation": number,
  "overall": number
}
```

## Why this is better

A repo might have:
- very high confidence in classification
- high confidence in install
- low confidence in run
- decent confidence in validation

This is much more useful than one number.

### Example:
For FastMCP:
- classification confidence should be high
- install confidence high
- run confidence low or zero
- validation confidence moderate/high
- overall confidence still strong

This matters because the repo is not a failure — it is correctly classified.

---

## Important confidence rule

Do not let the absence of a run step collapse overall confidence if classification is strong.

A library can be:
- highly confidently identified
- installable
- testable
- useful

That should still count as a strong result.

---

# 13. Notes field

The `notes` field is useful, but it should stay concise and purposeful.

It should contain:
- unusual setup requirements
- important caveats
- key context affecting interpretation
- why the category makes sense
- relevant warnings about usage mode

It should not become:
- marketing copy
- vague summaries
- user-personalized recommendation text

This field helps both debugging and future UI explanation.

---

# 14. What should NOT be in this schema

A key decision: keep this schema focused on execution and validation.

Do **not** mix in:
- personalized recommendation text
- "why this is interesting for Mike"
- product positioning
- downstream UI copy
- ranking logic beyond confidence/category

Those belong in:
- upstream orchestration
- recommendation layer
- presentation layer

This schema should remain a clean execution contract.

---

# 15. Example: FastMCP interpretation

FastMCP was a useful schema test case because it exposed weaknesses in a simplistic runnable/non-runnable model.

It is:
- not a standalone app
- a valid framework
- installable
- testable
- valuable to classify correctly

So the correct interpretation is not "red" or "failed."

It is:

- `execution_category = "dev_framework"`
- likely `execution_profile = "install_validate"`
- `execution.mode = "none"`
- `port = null`
- smoke tests should validate import, CLI, and basic object construction
- classification confidence high
- install confidence high
- run confidence zero or near-zero
- overall confidence still reasonably high

This is an example of the system being smart by **not** trying to launch the wrong thing.

---

# 16. Recommended schema direction

Below is the recommended schema direction after the design discussions.

This is not necessarily the final implementation schema, but it represents the design intent that future implementation should follow.

```json
{
  "repo_url": "string",

  "execution_category": "instant_ui | service_api | cli_tool | interactive_setup | dev_framework | non_viable",

  "execution_profile": "full_run | install_validate | smoke_only | skip_execution",

  "execution": {
    "install": ["string"],
    "run": ["string"],
    "mode": "background | blocking | none"
  },

  "port": {
    "expected": "number | null",
    "strategy": "fixed | detect | none"
  },

  "env": {
    "required": ["string"],
    "optional": ["string"]
  },

  "validation": {
    "smoke_tests": [
      {
        "name": "string",
        "order": "number (optional)",
        "command": "string",
        "success_criteria": {
          "exit_code": "number",
          "stdout_contains": ["string"]
        },
        "confidence": "number"
      }
    ]
  },

  "confidence": {
    "classification": "number",
    "install": "number",
    "run": "number",
    "validation": "number",
    "overall": "number"
  },

  "expected_behavior": {
    "long_running": "boolean",
    "opens_port": "boolean"
  },

  "notes": ["string"]
}
```

---

# 17. Guidance for the orchestration agent

When producing this schema, the orchestration agent should:

1. Read the README first
2. Inspect config/build files
3. Look for quickstart/run/install clues
4. Classify decisively
5. Avoid hallucinating commands
6. Prefer simple standard commands
7. Make smoke tests realistic and minimal
8. Use confidence to express uncertainty rather than inventing certainty
9. Treat framework/library repos as valid categories, not automatic failures
10. Make the schema useful to a deterministic downstream runner

The orchestration agent has access to the repo and can do multi-step reasoning, so it should be expected to infer category and validation strategy from actual repo evidence rather than surface-level keywords alone.

---

# 18. Guidance for the execution runner (`run.sh` / RepoRunner)

The runner should eventually adapt its behavior based on:

- `execution_category`
- `execution_profile`
- `execution.mode`
- `validation.smoke_tests`

### Examples:

## For `instant_ui` / `service_api`
- install
- run in background
- detect port
- expose preview URL
- run health validation

## For `cli_tool`
- install
- execute run command in blocking mode
- capture stdout/stderr
- validate expected output

## For `interactive_setup`
- install/run if possible
- mark as partial if manual steps remain
- surface missing env/setup clearly

## For `dev_framework`
- install
- do not launch a long-running process
- execute smoke tests
- report success if validation passes

## For `non_viable`
- skip execution or do minimal metadata-only handling

This is important because the execution layer should follow the schema rather than applying one-size-fits-all logic.

---

# 19. Final design philosophy

The schema exists to make the system:

- more deterministic
- less fragile
- more transparent
- more resource-efficient
- more useful across many repo types

The most important conceptual change is this:

The Repo Viability Scanner should not treat every repo as a web app.
It should interpret what kind of thing the repo is, what success means for that type, and then execute accordingly.

That is the core idea behind this schema design.

---

# 20. Recommended next implementation stage

The next stage after this schema work should be:

1. finalize the schema fields
2. update the orchestration skill to output this structure consistently
3. modify the runner to interpret:
   - execution category
   - execution profile
   - smoke tests
4. test on:
   - a web app
   - an API repo
   - a CLI repo
   - a framework/library repo
5. observe where schema or runner behavior still feels too coarse

The next real unlock is making the runner **dynamic based on schema**, rather than hardcoded around web-app assumptions.

---

# 21. Final takeaway

This schema is not just metadata.

It is the translation layer between:

- intelligent repo interpretation
- and real sandbox execution

If designed well, it will let the system feel:
- smart
- explainable
- adaptable
- and trustworthy

If designed poorly, the system will keep trying to launch the wrong things and calling the wrong outcomes failures.

The entire point of this schema work is to prevent that.
