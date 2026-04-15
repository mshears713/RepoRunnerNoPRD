import os

# Keep config import deterministic in tests when local .env is absent.
os.environ.setdefault("GITHUB_TOKEN", "ghp_test_token_for_pytest")
