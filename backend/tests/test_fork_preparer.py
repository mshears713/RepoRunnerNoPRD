from unittest.mock import MagicMock

from fork_preparer import prepare_fork


def test_prepare_fork_injects_required_files():
    client = MagicMock()
    client.commit_files_to_fork.return_value = {
        "repo": "bot/repo",
        "branch": "main",
        "files": [".devcontainer/devcontainer.json", "run.sh"],
    }

    result = prepare_fork(client, "bot/repo")

    client.commit_files_to_fork.assert_called_once()
    kwargs = client.commit_files_to_fork.call_args.kwargs
    assert kwargs["fork_full_name"] == "bot/repo"
    assert kwargs["files"].keys() == {".devcontainer/devcontainer.json", "run.sh"}
    assert "postStartCommand" in kwargs["files"][".devcontainer/devcontainer.json"]
    assert 'bash run.sh' in kwargs["files"][".devcontainer/devcontainer.json"]
    assert 'echo "=== RUN START ==="' in kwargs["files"]["run.sh"]
    assert result["branch"] == "main"
