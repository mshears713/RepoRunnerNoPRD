"""
Prepares a forked repo for Codespace execution by committing:
  - .devcontainer/devcontainer.json  (tells Codespace to run run.sh on start)
  - run.sh                           (the execution wrapper script)
"""

from pathlib import Path

from github_client import GitHubClient

_ASSETS_DIR = Path(__file__).parent / "assets"


def prepare_fork(client: GitHubClient, fork_full_name: str) -> dict:
    """
    Commit the devcontainer config and run.sh into the fork.
    """
    devcontainer = (_ASSETS_DIR / "devcontainer.json").read_text()
    run_sh = (_ASSETS_DIR / "run.sh").read_text()

    return client.commit_files_to_fork(
        fork_full_name=fork_full_name,
        files={
            ".devcontainer/devcontainer.json": devcontainer,
            "run.sh": run_sh,
        },
        message="chore: inject automated codespace startup files",
    )
