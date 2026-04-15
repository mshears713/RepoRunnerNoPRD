"""
Orchestrates AI analysis after execution:
- Always runs repo summary
- Only runs failure diagnosis when execution did not succeed
"""

from gemini_analyzer import GeminiAnalyzer


def analyze(
    scan: dict,
    repo_metadata: dict,
    file_tree: list[str],
    analyzer: GeminiAnalyzer | None = None,
) -> dict:
    """
    Returns a dict with 'analysis' and optionally 'failure' keys.
    scan:          the current scan dict (contains execution results)
    repo_metadata: from GitHubClient.get_repo_metadata()
    file_tree:     from GitHubClient.get_file_tree()
    """
    if analyzer is None:
        analyzer = GeminiAnalyzer()

    execution = scan.get("execution", {})
    upstream = scan.get("input_metadata", {})

    summary = analyzer.summarize(
        repo_full_name=f"{scan['repo_owner']}/{scan['repo_name']}",
        description=repo_metadata.get("description", ""),
        language=repo_metadata.get("language", ""),
        topics=repo_metadata.get("topics", []),
        readme_excerpt=repo_metadata.get("readme_excerpt", ""),
        execution=execution,
        upstream_metadata=upstream,
    )

    result = {"analysis": summary, "failure": None}

    # Run failure diagnosis if the app didn't actually start
    did_start = (
        execution.get("stage_reached") == "started" and execution.get("exit_code") == 0
    )
    if not did_start:
        failure = analyzer.diagnose_failure(
            repo_full_name=f"{scan['repo_owner']}/{scan['repo_name']}",
            language=repo_metadata.get("language", ""),
            file_tree=file_tree,
            execution=execution,
        )
        result["failure"] = failure

    return result
