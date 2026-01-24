"""Git worktree management for wiggy."""

import os
import re
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(Exception):
    """Base exception for git operations."""


class NotAGitRepoError(GitError):
    """Raised when not in a git repository."""


class WorktreeError(GitError):
    """Raised when worktree operations fail."""


@dataclass(frozen=True)
class WorktreeInfo:
    """Information about a git worktree."""

    path: Path
    branch: str
    hash_id: str
    main_repo: Path


class WorktreeManager:
    """Manages git worktrees for wiggy sessions."""

    def __init__(self, repo_path: Path | None = None) -> None:
        """Initialize with optional repo path (defaults to cwd)."""
        self._repo_path = repo_path or Path.cwd()
        if not self.is_git_repo(self._repo_path):
            raise NotAGitRepoError(f"Not a git repository: {self._repo_path}")
        self._repo_root = self.get_repo_root(self._repo_path)

    @staticmethod
    def is_git_repo(path: Path) -> bool:
        """Check if path is inside a git repository."""
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=path,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    @staticmethod
    def get_repo_root(path: Path) -> Path:
        """Get the root of the git repository containing path."""
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise GitError(f"Failed to get repo root: {result.stderr}")
        return Path(result.stdout.strip())

    @staticmethod
    def get_remote_url(repo_path: Path, remote: str = "origin") -> str | None:
        """Get the remote URL, or None if not configured."""
        result = subprocess.run(
            ["git", "remote", "get-url", remote],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    def get_repo_name(self) -> str:
        """Get the repository name from the directory."""
        return self._repo_root.name

    def generate_branch_name(self, suffix: str = "") -> tuple[str, str]:
        """Generate branch name: wiggy/<hash>[_<suffix>].

        Returns:
            Tuple of (branch_name, hash_id)
        """
        hash_id = secrets.token_hex(4)  # 8 hex chars
        if suffix:
            safe_suffix = re.sub(r"[^a-zA-Z0-9_-]", "_", suffix)
            branch = f"wiggy/{hash_id}_{safe_suffix}"
        else:
            branch = f"wiggy/{hash_id}"
        return branch, hash_id

    def get_worktree_root(self, override: Path | None = None) -> Path:
        """Resolve worktree root directory.

        Priority:
        1. override parameter
        2. WIGGY_WORKTREE_ROOT environment variable
        3. Default: ~/.wiggy/worktrees/<repo-name>/
        """
        if override:
            return override.expanduser().resolve()

        env_root = os.environ.get("WIGGY_WORKTREE_ROOT")
        if env_root:
            return Path(env_root).expanduser().resolve()

        default_root = Path.home() / ".wiggy" / "worktrees" / self.get_repo_name()
        return default_root

    def create_worktree(
        self,
        worktree_root: Path | None = None,
        suffix: str = "",
    ) -> WorktreeInfo:
        """Create a new worktree with a unique branch.

        Args:
            worktree_root: Root directory for worktrees. Defaults to resolved root.
            suffix: Optional suffix for branch name (e.g., "exec1" for parallel).

        Returns:
            WorktreeInfo with path and branch information.

        Raises:
            WorktreeError: If worktree creation fails.
        """
        root = self.get_worktree_root(worktree_root)
        branch, hash_id = self.generate_branch_name(suffix)

        # Create worktree directory name from branch (replace / with _)
        worktree_dir = branch.replace("/", "_")
        worktree_path = root / worktree_dir

        # Ensure root directory exists
        root.mkdir(parents=True, exist_ok=True)

        # Create the worktree with a new branch
        result = subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(worktree_path)],
            cwd=self._repo_root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise WorktreeError(f"Failed to create worktree: {result.stderr}")

        return WorktreeInfo(
            path=worktree_path,
            branch=branch,
            hash_id=hash_id,
            main_repo=self._repo_root,
        )

    def use_existing_worktree(self, worktree_path: Path) -> WorktreeInfo:
        """Validate and use an existing worktree.

        Args:
            worktree_path: Path to the existing worktree.

        Returns:
            WorktreeInfo for the existing worktree.

        Raises:
            WorktreeError: If path is not a valid worktree.
        """
        worktree_path = worktree_path.expanduser().resolve()

        if not worktree_path.exists():
            raise WorktreeError(f"Worktree path does not exist: {worktree_path}")

        # Check if it's a valid worktree by looking for .git file
        git_file = worktree_path / ".git"
        if not git_file.exists():
            raise WorktreeError(f"Not a valid worktree (no .git): {worktree_path}")

        # Get the branch name
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise WorktreeError(f"Failed to get branch: {result.stderr}")

        branch = result.stdout.strip()

        # Extract hash_id from branch name if it follows wiggy/<hash> pattern
        hash_id = ""
        if branch.startswith("wiggy/"):
            parts = branch[6:].split("_", 1)
            if parts:
                hash_id = parts[0]

        return WorktreeInfo(
            path=worktree_path,
            branch=branch,
            hash_id=hash_id,
            main_repo=self._repo_root,
        )

    def remove_worktree(self, info: WorktreeInfo, force: bool = False) -> None:
        """Remove a worktree.

        Args:
            info: WorktreeInfo for the worktree to remove.
            force: Force removal even if there are uncommitted changes.
        """
        cmd = ["git", "worktree", "remove"]
        if force:
            cmd.append("--force")
        cmd.append(str(info.path))

        result = subprocess.run(
            cmd,
            cwd=info.main_repo,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise WorktreeError(f"Failed to remove worktree: {result.stderr}")

        # Also delete the branch
        result = subprocess.run(
            ["git", "branch", "-D", info.branch],
            cwd=info.main_repo,
            capture_output=True,
            text=True,
        )
        # Don't raise on branch deletion failure - branch might be protected

    def list_worktrees(self) -> list[WorktreeInfo]:
        """List all wiggy-created worktrees for this repo."""
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=self._repo_root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return []

        worktrees: list[WorktreeInfo] = []
        current_path: Path | None = None
        current_branch: str | None = None

        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                current_path = Path(line[9:])
            elif line.startswith("branch refs/heads/"):
                current_branch = line[18:]
            elif line == "" and current_path and current_branch:
                # Only include wiggy branches
                if current_branch.startswith("wiggy/"):
                    hash_id = ""
                    parts = current_branch[6:].split("_", 1)
                    if parts:
                        hash_id = parts[0]
                    worktrees.append(
                        WorktreeInfo(
                            path=current_path,
                            branch=current_branch,
                            hash_id=hash_id,
                            main_repo=self._repo_root,
                        )
                    )
                current_path = None
                current_branch = None

        return worktrees
