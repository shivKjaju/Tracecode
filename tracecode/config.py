"""
config.py — Load and validate ~/.tracecode/config.toml.

Uses tomllib (Python 3.11+ stdlib, read-only TOML parser).
Falls back to safe defaults for any missing key — never raises on a
partially-configured file.

The config file is written once by `tracecode init` and then edited
manually by the user. We never auto-overwrite it.
"""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------

TRACECODE_DIR = Path.home() / ".tracecode"
DEFAULT_CONFIG_PATH = TRACECODE_DIR / "config.toml"
DEFAULT_DB_PATH = TRACECODE_DIR / "tracecode.db"
DEFAULT_LOG_PATH = TRACECODE_DIR / "tracecode.log"
DEFAULT_SERVER_PORT = 7842

# ---------------------------------------------------------------------------
# Default ignore lists for the filesystem watcher
# ---------------------------------------------------------------------------

DEFAULT_IGNORE_DIRS: list[str] = [
    ".git", "node_modules", "__pycache__", ".next", "dist",
    "build", "target", ".venv", "venv", ".pytest_cache",
    ".mypy_cache", "coverage", ".turbo",
]

DEFAULT_IGNORE_EXTENSIONS: list[str] = [
    ".pyc", ".pyo", ".swp", ".swo", ".lock",
]

# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------

@dataclass
class Config:
    db_path: Path
    server_port: int
    claude_binary: str           # empty string = auto-detect from PATH
    log_file: Path
    test_command: str | None     # global default test command, None if not set
    test_timeout: int            # seconds
    watch_ignore_dirs: list[str]
    watch_ignore_extensions: list[str]

    # Per-project overrides keyed by absolute project path string.
    # Each value is a dict that may contain: test_command, test_timeout
    project_overrides: dict[str, dict] = field(default_factory=dict)

    @property
    def tracecode_dir(self) -> Path:
        """The ~/.tracecode directory — parent of the database file."""
        return self.db_path.parent

    def get_test_command(self, project_path: str | Path) -> str | None:
        """
        Return the test command for a given project path.
        Project-specific override takes priority over the global default.
        Returns None if no command is configured.
        """
        key = str(Path(project_path).resolve())
        override = self.project_overrides.get(key, {})
        return override.get("test_command") or self.test_command or None

    def get_test_timeout(self, project_path: str | Path) -> int:
        """Return the test timeout for a project, falling back to global default."""
        key = str(Path(project_path).resolve())
        override = self.project_overrides.get(key, {})
        return int(override.get("test_timeout", self.test_timeout))

    def is_ignored_dir(self, dirname: str) -> bool:
        return dirname in self.watch_ignore_dirs

    def is_ignored_extension(self, ext: str) -> bool:
        return ext.lower() in self.watch_ignore_extensions


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> Config:
    """
    Load configuration from a TOML file.
    If the file does not exist, return the default config.
    Any missing key falls back to its default — partial configs are fine.
    """
    raw: dict = {}
    if Path(config_path).exists():
        with open(config_path, "rb") as f:
            raw = tomllib.load(f)

    tc = raw.get("tracecode", {})
    test = raw.get("test", {})
    watch = raw.get("watch", {})
    projects_raw = raw.get("projects", {})

    # Resolve db_path and log_file — expand ~ in user-supplied paths
    db_path_str = tc.get("db_path", str(DEFAULT_DB_PATH))
    log_file_str = tc.get("log_file", str(DEFAULT_LOG_PATH))

    return Config(
        db_path=Path(db_path_str).expanduser(),
        server_port=int(tc.get("server_port", DEFAULT_SERVER_PORT)),
        claude_binary=tc.get("claude_binary", ""),
        log_file=Path(log_file_str).expanduser(),
        test_command=test.get("command") or None,
        test_timeout=int(test.get("timeout_seconds", 30)),
        watch_ignore_dirs=watch.get("ignore_dirs", DEFAULT_IGNORE_DIRS),
        watch_ignore_extensions=watch.get("ignore_extensions", DEFAULT_IGNORE_EXTENSIONS),
        project_overrides={
            str(Path(k).expanduser().resolve()): v
            for k, v in projects_raw.items()
        },
    )


# ---------------------------------------------------------------------------
# Default config file template (written by `tracecode init`)
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_TOML = """\
# Tracecode configuration
# Generated by `tracecode init` — edit as needed.

[tracecode]
db_path       = "~/.tracecode/tracecode.db"
server_port   = 7842
claude_binary = ""   # Leave empty to auto-detect `claude` from PATH
log_file      = "~/.tracecode/tracecode.log"

[test]
# Global default test command — runs after every session to detect outcome.
# Leave commented out to rely on artifact detection instead.
# command = "pytest -q --tb=no"
timeout_seconds = 30

[watch]
# Directories to ignore at any depth in the project tree.
ignore_dirs = [
  ".git", "node_modules", "__pycache__", ".next", "dist",
  "build", "target", ".venv", "venv", ".pytest_cache",
  ".mypy_cache", "coverage", ".turbo",
]
# File extensions to ignore.
ignore_extensions = [".pyc", ".pyo", ".swp", ".swo", ".lock"]

# Per-project overrides — use absolute paths as section keys.
# [projects]
# [projects."/Users/you/myapp"]
# test_command = "npm test -- --watchAll=false --passWithNoTests"
# test_timeout = 60
"""


def write_default_config(config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    """
    Write the default config.toml to disk.
    Does NOT overwrite an existing file.
    """
    config_path = Path(config_path)
    if config_path.exists():
        return
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(DEFAULT_CONFIG_TOML)
