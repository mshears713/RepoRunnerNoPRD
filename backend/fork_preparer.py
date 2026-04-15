"""
Prepares a forked repo for Codespace execution by committing:
  - .devcontainer/devcontainer.json  (tells Codespace to run run.sh on start)
  - scanner/run.sh                   (the execution wrapper script)
"""

from pathlib import Path

from github_client import GitHubClient

_ASSETS_DIR = Path(__file__).parent / "assets"


def prepare_fork(client: GitHubClient, fork_full_name: str, repo_name: str) -> None:
    """
    Commit the devcontainer config and run.sh into the fork.
    repo_name is used to build the workspace path inside the Codespace.
    """
    devcontainer = (_ASSETS_DIR / "devcontainer.json").read_text()
    run_sh = (_ASSETS_DIR / "run.sh").read_text()

    client.commit_files_to_fork(
        fork_full_name=fork_full_name,
        files={
            ".devcontainer/devcontainer.json": devcontainer,
            "scanner/run.sh": run_sh,
        },
        message="chore: add scanner devcontainer and run script",
    )
