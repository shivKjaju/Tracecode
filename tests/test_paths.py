"""
tests/test_paths.py — Tests for tracecode/analysis/paths.py

Covers:
  - Directory component matching (infra/, auth/, .github/, etc.)
  - Exact filename matching (Dockerfile, Jenkinsfile, .gitlab-ci.yml)
  - Pattern matching (.env*, *.pem, docker-compose.*, id_rsa, etc.)
  - Negative cases (common non-protected files and directories)
  - Edge cases (root-level filenames, Windows paths, empty strings)
"""

import pytest

from tracecode.analysis.paths import is_protected_path


# ---------------------------------------------------------------------------
# Directory component matches
# ---------------------------------------------------------------------------

class TestProtectedDirectories:
    def test_infra_at_root(self) -> None:
        assert is_protected_path("infra/main.tf") is True

    def test_infra_nested(self) -> None:
        assert is_protected_path("src/infra/config.yml") is True

    def test_auth_at_root(self) -> None:
        assert is_protected_path("auth/middleware.py") is True

    def test_auth_nested(self) -> None:
        assert is_protected_path("src/auth/session.py") is True

    def test_security_directory(self) -> None:
        assert is_protected_path("security/policy.json") is True

    def test_secrets_directory(self) -> None:
        assert is_protected_path("secrets/api-keys.json") is True

    def test_credentials_directory(self) -> None:
        assert is_protected_path("credentials/service-account.json") is True

    def test_deploy_directory(self) -> None:
        assert is_protected_path("deploy/prod.sh") is True

    def test_deployment_directory(self) -> None:
        assert is_protected_path("deployment/k8s.yml") is True

    def test_k8s_directory(self) -> None:
        assert is_protected_path("k8s/deployment.yml") is True

    def test_kubernetes_directory(self) -> None:
        assert is_protected_path("kubernetes/ingress.yml") is True

    def test_terraform_directory(self) -> None:
        assert is_protected_path("terraform/main.tf") is True

    def test_ansible_directory(self) -> None:
        assert is_protected_path("ansible/playbook.yml") is True

    def test_helm_directory(self) -> None:
        assert is_protected_path("helm/values.yaml") is True

    def test_github_directory(self) -> None:
        assert is_protected_path(".github/workflows/ci.yml") is True

    def test_github_directory_other_file(self) -> None:
        assert is_protected_path(".github/CODEOWNERS") is True

    def test_circleci_directory(self) -> None:
        assert is_protected_path(".circleci/config.yml") is True

    def test_deeply_nested_protected_dir(self) -> None:
        assert is_protected_path("services/api/infra/networking.tf") is True


# ---------------------------------------------------------------------------
# Exact filename matches
# ---------------------------------------------------------------------------

class TestProtectedExactFilenames:
    def test_dockerfile(self) -> None:
        assert is_protected_path("Dockerfile") is True

    def test_dockerfile_in_subdir(self) -> None:
        assert is_protected_path("docker/Dockerfile") is True

    def test_jenkinsfile(self) -> None:
        assert is_protected_path("Jenkinsfile") is True

    def test_gitlab_ci(self) -> None:
        assert is_protected_path(".gitlab-ci.yml") is True


# ---------------------------------------------------------------------------
# Pattern matches
# ---------------------------------------------------------------------------

class TestProtectedPatterns:
    # .env variants
    def test_dotenv_bare(self) -> None:
        assert is_protected_path(".env") is True

    def test_dotenv_local(self) -> None:
        assert is_protected_path(".env.local") is True

    def test_dotenv_production(self) -> None:
        assert is_protected_path(".env.production") is True

    def test_dotenv_example(self) -> None:
        # .env.example still matches — it often contains real variable names
        assert is_protected_path(".env.example") is True

    def test_dotenv_in_subdir(self) -> None:
        assert is_protected_path("config/.env") is True

    def test_anything_dot_env_suffix(self) -> None:
        assert is_protected_path("backend.env") is True

    # Private key / certificate files
    def test_pem_file(self) -> None:
        assert is_protected_path("certs/server.pem") is True

    def test_key_file(self) -> None:
        assert is_protected_path("keys/private.key") is True

    def test_crt_file(self) -> None:
        assert is_protected_path("server.crt") is True

    def test_p12_file(self) -> None:
        assert is_protected_path("identity.p12") is True

    def test_pfx_file(self) -> None:
        assert is_protected_path("cert.pfx") is True

    # SSH private keys
    def test_id_rsa(self) -> None:
        assert is_protected_path("id_rsa") is True

    def test_id_rsa_in_subdir(self) -> None:
        assert is_protected_path(".ssh/id_rsa") is True

    def test_id_ed25519(self) -> None:
        assert is_protected_path("id_ed25519") is True

    def test_id_dsa(self) -> None:
        assert is_protected_path("id_dsa") is True

    def test_id_ecdsa(self) -> None:
        assert is_protected_path("id_ecdsa") is True

    # docker-compose variants
    def test_docker_compose_yml(self) -> None:
        assert is_protected_path("docker-compose.yml") is True

    def test_docker_compose_yaml(self) -> None:
        assert is_protected_path("docker-compose.yaml") is True

    def test_docker_compose_override(self) -> None:
        assert is_protected_path("docker-compose.override.yml") is True

    def test_docker_compose_prod(self) -> None:
        assert is_protected_path("docker-compose-prod.yml") is True


# ---------------------------------------------------------------------------
# Negative cases — common files that should NOT be protected
# ---------------------------------------------------------------------------

class TestNotProtected:
    def test_regular_python_file(self) -> None:
        assert is_protected_path("src/main.py") is False

    def test_readme(self) -> None:
        assert is_protected_path("README.md") is False

    def test_generic_yaml(self) -> None:
        assert is_protected_path("config.yml") is False

    def test_test_file(self) -> None:
        assert is_protected_path("tests/test_auth.py") is False

    def test_src_directory(self) -> None:
        assert is_protected_path("src/utils.py") is False

    def test_lib_directory(self) -> None:
        assert is_protected_path("lib/helpers.py") is False

    def test_package_json(self) -> None:
        # package.json is covered by is_sensitive_file(), not is_protected_path()
        assert is_protected_path("package.json") is False

    def test_requirements_txt(self) -> None:
        # requirements.txt is covered by is_sensitive_file(), not is_protected_path()
        assert is_protected_path("requirements.txt") is False

    def test_makefile(self) -> None:
        # Conservative: Makefile is NOT in the default protected list
        assert is_protected_path("Makefile") is False

    def test_generic_config_directory(self) -> None:
        # 'config/' is too broad — not in the protected list
        assert is_protected_path("config/settings.py") is False

    def test_infrastructure_not_infra(self) -> None:
        # 'infrastructure' is NOT a match — exact component match only
        assert is_protected_path("infrastructure/main.tf") is False

    def test_authentication_not_auth(self) -> None:
        # 'authentication' is NOT a match — exact component match only
        assert is_protected_path("authentication/login.py") is False


# ---------------------------------------------------------------------------
# Edge cases: filename-only (no directory component)
# ---------------------------------------------------------------------------

class TestEdgeCasesFilenameOnly:
    def test_auth_py_at_root_not_protected(self) -> None:
        # A file NAMED 'auth.py' is not protected — only files INSIDE auth/ are
        assert is_protected_path("auth.py") is False

    def test_infra_py_at_root_not_protected(self) -> None:
        assert is_protected_path("infra.py") is False

    def test_security_txt_at_root_not_protected(self) -> None:
        assert is_protected_path("security.txt") is False

    def test_empty_string(self) -> None:
        assert is_protected_path("") is False

    def test_just_a_filename(self) -> None:
        assert is_protected_path("main.py") is False


# ---------------------------------------------------------------------------
# Edge cases: Windows-style paths
# ---------------------------------------------------------------------------

class TestWindowsPaths:
    def test_windows_infra_path(self) -> None:
        assert is_protected_path("infra\\deploy\\main.tf") is True

    def test_windows_dotenv(self) -> None:
        assert is_protected_path("config\\.env") is True

    def test_windows_auth_path(self) -> None:
        assert is_protected_path("src\\auth\\session.py") is True
