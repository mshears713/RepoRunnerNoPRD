import storage
from codespaces_client import CodespacesClient
from github_client import GitHubClient


def cleanup_scan_resources(scan_id: str, reason: str = "scheduled") -> dict:
    scan = storage.get_scan(scan_id)
    if not scan:
        return {"codespace_deleted": False, "fork_deleted": False}

    cs_name = scan.get("codespace_name")
    fork_name = scan.get("fork_repo_name")
    cleanup = scan.get("cleanup", {})

    cs_deleted = cleanup.get("codespace_deleted", False)
    fk_deleted = cleanup.get("fork_deleted", False)

    if cs_name and not cs_deleted:
        cs_deleted = CodespacesClient().delete_codespace(cs_name)
    if fork_name and not fk_deleted:
        fk_deleted = GitHubClient().delete_fork(fork_name)

    storage.add_timeline_step(
        scan_id,
        "cleanup_executed",
        "completed",
        f"Cleanup executed ({reason})",
        details={"codespace_deleted": cs_deleted, "fork_deleted": fk_deleted},
    )
    storage.update_scan(
        scan_id,
        is_active=False,
        **{"cleanup.codespace_deleted": cs_deleted, "cleanup.fork_deleted": fk_deleted},
    )
    return {"codespace_deleted": cs_deleted, "fork_deleted": fk_deleted}
