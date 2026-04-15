"""Tests for GitHubClient using respx to mock all HTTP calls."""

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

    client = GitHubClient(token="ghp_fake_token", fork_owner="bot")
    meta = client.get_repo_metadata("owner", "repo")

    assert meta["full_name"] == "owner/repo"
    assert meta["language"] == "Python"
    assert "README" in meta["readme_excerpt"]


@patch("github_client.Github")
def test_get_file_tree(mock_gh_class):
    from github_client import GitHubClient

    mock_repo = make_mock_repo()
    mock_gh_class.return_value.get_repo.return_value = mock_repo

    client = GitHubClient(token="ghp_fake_token", fork_owner="bot")
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

    client = GitHubClient(token="ghp_fake_token", fork_owner="bot")
    result = client.fork_repo("owner", "repo")

    assert result == "bot/repo"


@patch("github_client.Github")
def test_wait_for_fork_success(mock_gh_class):
    from github_client import GitHubClient

    mock_fork = make_mock_repo("bot/repo")
    mock_gh_class.return_value.get_repo.return_value = mock_fork

    client = GitHubClient(token="ghp_fake_token", fork_owner="bot")
    assert client.wait_for_fork("bot/repo", timeout=10) is True


@patch("github_client.Github")
def test_wait_for_fork_timeout(mock_gh_class):
    from github import GithubException

    from github_client import GitHubClient

    mock_gh_class.return_value.get_repo.side_effect = GithubException(404, "not found")

    client = GitHubClient(token="ghp_fake_token", fork_owner="bot")
    result = client.wait_for_fork("bot/repo", timeout=1)
    assert result is False


@patch("github_client.Github")
def test_delete_fork(mock_gh_class):
    from github_client import GitHubClient

    mock_fork = MagicMock()
    mock_gh_class.return_value.get_repo.return_value = mock_fork

    client = GitHubClient(token="ghp_fake_token", fork_owner="bot")
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

    client = GitHubClient(token="ghp_fake_token", fork_owner="bot")
    client.commit_files_to_fork("bot/repo", {"scanner/run.sh": "#!/bin/bash\necho hi"})

    mock_fork.create_file.assert_called_once()


@patch("github_client.Github")
def test_get_file_from_fork_returns_content(mock_gh_class):
    import base64

    from github_client import GitHubClient

    mock_fork = MagicMock()
    mock_contents = MagicMock()
    mock_contents.content = base64.b64encode(b'{"stage_reached": "started"}').decode()
    mock_fork.get_contents.return_value = mock_contents
    mock_gh_class.return_value.get_repo.return_value = mock_fork

    client = GitHubClient(token="ghp_fake_token", fork_owner="bot")
    result = client.get_file_from_fork("bot/repo", "scanner_result.json")

    assert result is not None
    assert "stage_reached" in result


@patch("github_client.Github")
def test_get_file_from_fork_returns_none_when_missing(mock_gh_class):
    from github import GithubException

    from github_client import GitHubClient

    mock_fork = MagicMock()
    mock_fork.get_contents.side_effect = GithubException(404, "not found")
    mock_gh_class.return_value.get_repo.return_value = mock_fork

    client = GitHubClient(token="ghp_fake_token", fork_owner="bot")
    result = client.get_file_from_fork("bot/repo", "scanner_result.json")

    assert result is None


@patch("github_client.Github")
def test_fork_repo_tries_org_first(mock_gh_class):
    """fork_repo should attempt to get an organization and fork into it."""
    from github_client import GitHubClient

    mock_repo = make_mock_repo()
    fork = MagicMock()
    fork.full_name = "my-org/repo"
    mock_repo.create_fork.return_value = fork

    mock_org = MagicMock()
    mock_org.login = "my-org"
    mock_gh_class.return_value.get_repo.return_value = mock_repo
    mock_gh_class.return_value.get_organization.return_value = mock_org

    client = GitHubClient(token="ghp_fake_token", fork_owner="my-org")
    result = client.fork_repo("upstream", "repo")

    assert result == "my-org/repo"
    mock_repo.create_fork.assert_called_once_with(organization="my-org")


@patch("github_client.Github")
def test_fork_repo_falls_back_to_personal_account(mock_gh_class):
    """fork_repo should fall back to personal fork when org lookup fails."""
    from github import GithubException

    from github_client import GitHubClient

    mock_repo = make_mock_repo()
    fork = MagicMock()
    fork.full_name = "myuser/repo"
    mock_repo.create_fork.return_value = fork

    mock_gh_class.return_value.get_repo.return_value = mock_repo
    mock_gh_class.return_value.get_organization.side_effect = GithubException(404, "not found")

    client = GitHubClient(token="ghp_fake_token", fork_owner="myuser")
    result = client.fork_repo("upstream", "repo")

    assert result == "myuser/repo"
    # Should have been called with no organization arg
    mock_repo.create_fork.assert_called_once_with()


def test_github_client_rejects_invalid_token():
    from github_client import GitHubClient, GitHubDiagnosticsError

    try:
        GitHubClient(token="not-valid-token", fork_owner="bot")
    except GitHubDiagnosticsError as exc:
        assert exc.step == "github_auth"
        assert exc.reason == "GITHUB_TOKEN missing or invalid"
        assert exc.details["length"] > 0
    else:
        raise AssertionError("Expected GitHubDiagnosticsError for invalid token")


@patch("github_client.Github")
def test_github_client_auth_failure_returns_structured_error(mock_gh_class):
    from github import GithubException
    from github_client import GitHubClient, GitHubDiagnosticsError

    mock_gh_class.return_value.get_user.side_effect = GithubException(401, "bad credentials")

    try:
        GitHubClient(token="ghp_fake_token", fork_owner="bot")
    except GitHubDiagnosticsError as exc:
        payload = exc.to_failure()
        assert payload["step"] == "github_auth"
        assert payload["reason"] == "GitHub authentication failed"
        assert payload["details"]["error_message"]
    else:
        raise AssertionError("Expected GitHubDiagnosticsError for auth failure")
