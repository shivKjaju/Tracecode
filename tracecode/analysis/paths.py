"""
analysis/paths.py — Convention-based protected path detection.

Identifies files and directories that deserve extra human review when touched
by an AI coding session, based on project structure conventions alone.

This is intentionally separate from is_sensitive_file() in scoring.py:
  - is_sensitive_file()  → file-content signals (.env, *.pem, package.json)
                           Used to fire the "sensitive files" anomaly.
  - is_protected_path()  → structural/directory signals (infra/, auth/, .github/)
                           Used to boost Review First priority and surface in the
                           terminal summary.

Protected path hits do NOT change the verdict engine. They add a
"protected path" reason label (+25 points) to compute_review_first() and
appear prominently in the terminal summary when the verdict warrants it.
"""

import re


# ---------------------------------------------------------------------------
# Directory component matches
#
# A path is protected if ANY directory component (not the filename itself)
# equals one of these names. Exact match only — 'infrastructure' does not
# match 'infra', 'authentication' does not match 'auth'.
#
# Example: 'src/auth/middleware.py' → component 'auth' → protected ✓
# Example: 'auth.py' (root)        → no directory components  → not protected ✗
# ---------------------------------------------------------------------------

_PROTECTED_DIRS: frozenset[str] = frozenset({
    "infra",
    "auth",
    "security",
    "secrets",
    "credentials",
    "deploy",
    "deployment",
    "k8s",
    "kubernetes",
    "terraform",
    "ansible",
    "helm",
    ".github",
    ".circleci",
})

# ---------------------------------------------------------------------------
# Exact filename matches
# ---------------------------------------------------------------------------

_PROTECTED_EXACT: frozenset[str] = frozenset({
    "Dockerfile",
    "Jenkinsfile",
    ".gitlab-ci.yml",
})

# ---------------------------------------------------------------------------
# Pattern matches (applied to full normalised path)
# ---------------------------------------------------------------------------

_PROTECTED_PATTERNS: list[re.Pattern] = [
    # .env (bare), .env.local, .env.production, anything.env
    re.compile(r'(^|[/\\])\.env$'),
    re.compile(r'(^|[/\\])\.env\.'),
    re.compile(r'\.env$'),
    # Private key / certificate files
    re.compile(r'\.(pem|key|crt|p12|pfx)$', re.IGNORECASE),
    # SSH private keys by convention
    re.compile(r'(^|[/\\])id_(rsa|ed25519|dsa|ecdsa)$'),
    # docker-compose.yml, docker-compose.override.yml, docker-compose-prod.yml
    re.compile(r'(^|[/\\])docker-compose(\.ya?ml|-[^/\\]*)$', re.IGNORECASE),
]


def is_protected_path(path: str) -> bool:
    """
    Return True if the file path matches any convention-based protected pattern.

    Checks in order:
      1. Any directory component (not the filename) is in the protected dirs set.
      2. The filename exactly matches a protected exact filename.
      3. The full path matches a protected regex pattern.

    Path separators are normalised to '/' before matching.
    Never raises — malformed paths return False.
    """
    try:
        normalized = path.replace("\\", "/").rstrip("/")
        parts = normalized.split("/")

        if not parts:
            return False

        filename = parts[-1]
        # Directory components are everything except the last segment (filename).
        dir_parts = parts[:-1]

        # 1. Directory component match
        for part in dir_parts:
            if part in _PROTECTED_DIRS:
                return True

        # 2. Exact filename match
        if filename in _PROTECTED_EXACT:
            return True

        # 3. Pattern match against full normalised path
        for pattern in _PROTECTED_PATTERNS:
            if pattern.search(normalized):
                return True

    except Exception:
        pass  # malformed path — not our problem

    return False
