"""Tests for GeminiAnalyzer with mocked google-genai API responses."""

import json
import pytest
from unittest.mock import MagicMock, patch


FIXTURE_SUMMARY = {
    "what_it_does": "A lightweight FastAPI server for embeddings.",
    "use_case": "Backend service for AI applications needing vector embeddings.",
    "tech_stack": ["Python", "FastAPI", "PyTorch"],
    "caveats": ["Requires OPENAI_API_KEY environment variable"],
}

FIXTURE_FAILURE = {
    "category": "missing_env_vars",
    "plain_explanation": "The app failed to start because OPENAI_API_KEY was not set.",
    "fix_suggestions": ["Set OPENAI_API_KEY in .env", "Check the README for required environment variables"],
}


def _make_analyzer(response_text: str):
    """Create a GeminiAnalyzer with a mocked client."""
    from gemini_analyzer import GeminiAnalyzer
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = response_text
    mock_client.models.generate_content.return_value = mock_response
    analyzer._client = mock_client
    analyzer._model = "gemini-2.0-flash"
    return analyzer


def test_summarize_parses_json():
    analyzer = _make_analyzer(json.dumps(FIXTURE_SUMMARY))

    result = analyzer.summarize(
        repo_full_name="owner/repo",
        description="Embeddings service",
        language="Python",
        topics=["ml", "api"],
        readme_excerpt="# Embeddings API\nFast and lightweight.",
        execution={"stage_reached": "started", "exit_code": 0, "stdout_tail": "", "port": 8000},
    )

    assert result["what_it_does"] == FIXTURE_SUMMARY["what_it_does"]
    assert result["tech_stack"] == FIXTURE_SUMMARY["tech_stack"]
    assert result["caveats"] == FIXTURE_SUMMARY["caveats"]


def test_summarize_handles_markdown_fenced_json():
    # Model wraps output in markdown code fence
    analyzer = _make_analyzer("```json\n" + json.dumps(FIXTURE_SUMMARY) + "\n```")

    result = analyzer.summarize(
        repo_full_name="owner/repo",
        description="",
        language="Python",
        topics=[],
        readme_excerpt="",
        execution={"stage_reached": "started", "exit_code": 0, "stdout_tail": "", "port": 8000},
    )

    assert result["what_it_does"] == FIXTURE_SUMMARY["what_it_does"]


def test_summarize_falls_back_on_malformed_json():
    analyzer = _make_analyzer("This is not JSON at all.")

    result = analyzer.summarize(
        repo_full_name="owner/repo",
        description="",
        language="Python",
        topics=[],
        readme_excerpt="",
        execution={"stage_reached": "cloned", "exit_code": 1, "stdout_tail": "", "stderr_tail": ""},
    )

    # Should fall back to default — what_it_does gets the raw text
    assert "what_it_does" in result


def test_diagnose_failure_parses_json():
    analyzer = _make_analyzer(json.dumps(FIXTURE_FAILURE))

    result = analyzer.diagnose_failure(
        repo_full_name="owner/repo",
        language="Python",
        file_tree=["main.py", "requirements.txt"],
        execution={
            "stage_reached": "installed",
            "exit_code": 1,
            "stderr_tail": "KeyError: OPENAI_API_KEY",
            "stdout_tail": "",
        },
    )

    assert result["category"] == "missing_env_vars"
    assert len(result["fix_suggestions"]) > 0


def test_diagnose_failure_normalizes_bad_category():
    bad = dict(FIXTURE_FAILURE, category="some_made_up_category")
    analyzer = _make_analyzer(json.dumps(bad))

    result = analyzer.diagnose_failure(
        repo_full_name="owner/repo",
        language="Python",
        file_tree=[],
        execution={"stage_reached": "cloned", "exit_code": 1, "stderr_tail": "", "stdout_tail": ""},
    )

    assert result["category"] == "unknown"
