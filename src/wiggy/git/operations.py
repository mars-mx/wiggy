"""Post-execution git operations for wiggy."""

import shutil
import subprocess

from wiggy.git.worktree import WorktreeInfo


class RemoteError(Exception):
    """Raised when remote operations fail."""


class GitOperations:
    """Post-execution git operations (push, PR)."""

    def __init__(self, worktree_info: WorktreeInfo) -> None:
        """Initialize with worktree information."""
        self._info = worktree_info

    def has_commits(self) -> bool:
        """Check if the worktree has commits ahead of base branch.

        Returns True if there are commits that haven't been pushed.
        """
        # Get the merge base with the default branch
        result = subprocess.run(
            ["git", "log", "--oneline", "HEAD", "-1"],
            cwd=self._info.path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False

        # Check if there are any commits on this branch
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=self._info.path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False

        try:
            commit_count = int(result.stdout.strip())
            return commit_count > 0
        except ValueError:
            return False

    def get_commit_count_ahead(self, base_branch: str = "main") -> int:
        """Get the number of commits ahead of the base branch.

        Args:
            base_branch: The branch to compare against.

        Returns:
            Number of commits ahead, or 0 if unable to determine.
        """
        # First check if base branch exists
        result = subprocess.run(
            ["git", "rev-parse", "--verify", base_branch],
            cwd=self._info.path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            # Try origin/main or origin/master
            remote_branches = [f"origin/{base_branch}", "origin/main", "origin/master"]
            for remote_branch in remote_branches:
                result = subprocess.run(
                    ["git", "rev-parse", "--verify", remote_branch],
                    cwd=self._info.path,
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    base_branch = remote_branch
                    break
            else:
                return 0

        result = subprocess.run(
            ["git", "rev-list", "--count", f"{base_branch}..HEAD"],
            cwd=self._info.path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return 0

        try:
            return int(result.stdout.strip())
        except ValueError:
            return 0

    def push_to_remote(self, remote: str = "origin") -> bool:
        """Push the worktree branch to remote.

        Args:
            remote: The remote to push to.

        Returns:
            True on success, False on failure.
        """
        result = subprocess.run(
            ["git", "push", "-u", remote, self._info.branch],
            cwd=self._info.path,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    def create_pull_request(
        self,
        title: str | None = None,
        body: str | None = None,
        base_branch: str = "main",
    ) -> str | None:
        """Create a PR using gh CLI.

        Args:
            title: PR title. Defaults to branch name.
            body: PR body/description.
            base_branch: Base branch for the PR.

        Returns:
            PR URL on success, None on failure.
        """
        # Check if gh CLI is available
        if not shutil.which("gh"):
            return None

        cmd = ["gh", "pr", "create"]

        if title:
            cmd.extend(["--title", title])
        else:
            cmd.extend(["--title", f"Wiggy: {self._info.branch}"])

        if body:
            cmd.extend(["--body", body])
        else:
            pr_body = f"Automated PR from wiggy session {self._info.hash_id}"
            cmd.extend(["--body", pr_body])

        cmd.extend(["--base", base_branch])
        cmd.extend(["--head", self._info.branch])

        result = subprocess.run(
            cmd,
            cwd=self._info.path,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            return None

        # gh pr create outputs the PR URL
        return result.stdout.strip()

    def get_commit_messages(self, base_branch: str = "main") -> list[str]:
        """Get commit messages for commits ahead of base branch.

        Args:
            base_branch: The branch to compare against.

        Returns:
            List of commit messages.
        """
        # Determine the actual base ref
        base_ref = base_branch
        candidates = [
            base_branch,
            f"origin/{base_branch}",
            "origin/main",
            "origin/master",
        ]
        for candidate in candidates:
            result = subprocess.run(
                ["git", "rev-parse", "--verify", candidate],
                cwd=self._info.path,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                base_ref = candidate
                break

        result = subprocess.run(
            ["git", "log", "--oneline", f"{base_ref}..HEAD"],
            cwd=self._info.path,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            return []

        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
