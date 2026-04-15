"""Tests for GitHubClient using respx to mock all HTTP calls."""

import pytest
import respx
import httpx
from unittest.mock import MagicMock, patch

# We test the raw httpx portions; PyGithub portions use mock objects


def make_mock_repo(full_name="owner/repo", language="Python", description="Test repo"):
    repo = MagicMock()
    repo.full_name = full_name
    repo.description = description
    repo.language = language
    repo.stargazers_count = 42
    repo.default_branch = "main"
    repo.get_topics.return_value = ["python", "api"]
    readme = MagicMock()
    import base64
    readme.content = base64.b64encode(b"# Test README\nThis is a test.").decode()
    repo.get_readme.return_value = readme

    tree_item = MagicMock()
    tree_item.path = "main.py"
    tree_item.type = "blob"
    tree_obj = MagicMock()
    tree_obj.tree = [tree_item]
    repo.get_git_tree.return_value = tree_obj

    return repo


@patch("github_client.Github")
def test_get_repo_metadata(mock_gh_class):
    from github_client import GitHubClient

    mock_repo = make_mock_repo()
    mock_gh_class.return_value.get_repo.return_value = mock_repo

    client = GitHubClient(token="fake", fork_owner="bot")
    meta = client.get_repo_metadata("owner", "repo")

    assert meta["full_name"] == "owner/repo"
    assert meta["language"] == "Python"
    assert "README" in meta["readme_excerpt"]


@patch("github_client.Github")
def test_get_file_tree(mock_gh_class):
    from github_client import GitHubClient

    mock_repo = make_mock_repo()
    mock_gh_class.return_value.get_repo.return_value = mock_repo

    client = GitHubClient(token="fake", fork_owner="bot")
    tree = client.get_file_tree("owner", "repo")

    assert "main.py" in tree


@patch("github_client.Github")
def test_fork_repo(mock_gh_class):
    from github_client import GitHubClient

    mock_repo = make_mock_repo()
    fork = MagicMock()
    fork.full_name = "bot/repo"
    mock_repo.create_fork.return_value = fork
    mock_gh_class.return_value.get_repo.return_value = mock_repo

    client = GitHubClient(token="fake", fork_owner="bot")
    result = client.fork_repo("owner", "repo")

    assert result == "bot/repo"


@patch("github_client.Github")
def test_wait_for_fork_success(mock_gh_class):
    from github_client import GitHubClient

    mock_fork = make_mock_repo("bot/repo")
    mock_gh_class.return_value.get_repo.return_value = mock_fork

    client = GitHubClient(token="fake", fork_owner="bot")
    assert client.wait_for_fork("bot/repo", timeout=10) is True


@patch("github_client.Github")
def test_wait_for_fork_timeout(mock_gh_class):
    from github import GithubException
    from github_client import GitHubClient

    mock_gh_class.return_value.get_repo.side_effect = GithubException(404, "not found")

    client = GitHubClient(token="fake", fork_owner="bot")
    result = client.wait_for_fork("bot/repo", timeout=1)
    assert result is False


@patch("github_client.Github")
def test_delete_fork(mock_gh_class):
    from github_client import GitHubClient

    mock_fork = MagicMock()
    mock_gh_class.return_value.get_repo.return_value = mock_fork

    client = GitHubClient(token="fake", fork_owner="bot")
    assert client.delete_fork("bot/repo") is True
    mock_fork.delete.assert_called_once()


@patch("github_client.Github")
def test_commit_files_to_fork_creates_new_file(mock_gh_class):
    from github import GithubException
    from github_client import GitHubClient

    mock_fork = MagicMock()
    mock_fork.default_branch = "main"
    mock_fork.get_contents.side_effect = GithubException(404, "not found")
    mock_gh_class.return_value.get_repo.return_value = mock_fork

    client = GitHubClient(token="fake", fork_owner="bot")
    client.commit_files_to_fork("bot/repo", {"scanner/run.sh": "#!/bin/bash\necho hi"})

    mock_fork.create_file.assert_called_once()
