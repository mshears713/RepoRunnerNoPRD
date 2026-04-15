"""
Gemini Flash AI analysis layer.
Two prompts: repo summary and failure diagnosis.
Uses the google-genai SDK (replaces deprecated google-generativeai).
"""

import json
import re
from pathlib import Path

from google import genai
from google.genai import types as genai_types

from config import settings

_PROMPTS_DIR = Path(__file__).parent / "prompts"

# Failure categories
FAILURE_CATEGORIES = frozenset([
    "missing_env_vars", "bad_deps", "runtime_crash", "timeout",
    "port_conflict", "build_failure", "unknown",
])


class GeminiAnalyzer:
    def __init__(self, api_key: str | None = None):
        self._client = genai.Client(api_key=api_key or settings.gemini_api_key)
        self._model = "gemini-2.0-flash"

    # ------------------------------------------------------------------
    # Repo summary
    # ------------------------------------------------------------------

    def summarize(
        self,
        repo_full_name: str,
        description: str,
        language: str,
        topics: list[str],
        readme_excerpt: str,
        execution: dict,
        upstream_metadata: dict | None = None,
    ) -> dict:
        """
        Returns: { what_it_does, use_case, tech_stack, caveats }
        """
        template = (_PROMPTS_DIR / "summary.txt").read_text()

        exec_status = "success" if execution.get("exit_code") == 0 else "failed"
        upstream_str = ""
        if upstream_metadata:
            upstream_str = "\n".join(
                f"{k}: {v}" for k, v in upstream_metadata.items() if v
            )

        prompt = template.format(
            repo_full_name=repo_full_name,
            description=description or "(none)",
            language=language or "unknown",
            topics=", ".join(topics) if topics else "(none)",
            readme_excerpt=readme_excerpt[:3000] if readme_excerpt else "(not available)",
            execution_status=exec_status,
            stage_reached=execution.get("stage_reached", "unknown"),
            port=execution.get("port") or "none",
            stdout_tail=execution.get("stdout_tail", "")[-2000:],
            upstream_metadata=upstream_str or "(none)",
        )

        raw = self._generate(prompt)
        return self._parse_json(
            raw,
            default={"what_it_does": raw[:500], "use_case": "", "tech_stack": [], "caveats": []},
        )

    # ------------------------------------------------------------------
    # Failure diagnosis
    # ------------------------------------------------------------------

    def diagnose_failure(
        self,
        repo_full_name: str,
        language: str,
        file_tree: list[str],
        execution: dict,
    ) -> dict:
        """
        Returns: { category, plain_explanation, fix_suggestions }
        Only call when execution failed (exit_code != 0 or stage_reached != 'started').
        """
        template = (_PROMPTS_DIR / "failure.txt").read_text()

        prompt = template.format(
            repo_full_name=repo_full_name,
            language=language or "unknown",
            file_tree="\n".join(file_tree[:60]),
            stage_reached=execution.get("stage_reached", "unknown"),
            exit_code=execution.get("exit_code", 1),
            stderr_tail=execution.get("stderr_tail", "")[-3000:],
            stdout_tail=execution.get("stdout_tail", "")[-1000:],
        )

        raw = self._generate(prompt)
        result = self._parse_json(
            raw,
            default={
                "category": "unknown",
                "plain_explanation": raw[:500],
                "fix_suggestions": [],
            },
        )

        # Normalise category
        if result.get("category") not in FAILURE_CATEGORIES:
            result["category"] = "unknown"

        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _generate(self, prompt: str) -> str:
        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=1024,
            ),
        )
        return response.text.strip()

    def _parse_json(self, text: str, default: dict) -> dict:
        """
        Try to extract a JSON object from the model's response.
        Handles cases where the model wraps output in markdown code fences.
        """
        # Strip markdown code fence if present
        cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)

        # Find the outermost { ... }
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return default
