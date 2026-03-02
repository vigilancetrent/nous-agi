"""Verify the ouroboros → nous rename is complete."""

import ast
import os
import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent


def test_no_ouroboros_in_python_imports():
    """No Python file should import from 'ouroboros'."""
    violations = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", "node_modules")]
        for f in files:
            if not f.endswith(".py"):
                continue
            path = pathlib.Path(root) / f
            try:
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module and "ouroboros" in node.module:
                        violations.append(f"{path}:{node.lineno}: from {node.module}")
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            if "ouroboros" in alias.name:
                                violations.append(f"{path}:{node.lineno}: import {alias.name}")
            except SyntaxError:
                continue
    assert not violations, f"Found ouroboros imports:\n" + "\n".join(violations)


def test_nous_package_exists():
    """The nous/ package directory must exist."""
    assert (REPO / "nous").is_dir()
    assert (REPO / "nous" / "__init__.py").exists()
    assert not (REPO / "ouroboros").exists(), "Old ouroboros/ directory still exists"


def test_all_nous_modules_importable():
    """All core nous modules should be importable."""
    import importlib
    modules = [
        "nous",
        "nous.agent",
        "nous.llm",
        "nous.loop",
        "nous.memory",
        "nous.context",
        "nous.consciousness",
        "nous.review",
        "nous.utils",
        "nous.runtime",
        "nous.embeddings",
        "nous.experience",
        "nous.vector_memory",
        "nous.goals",
        "nous.metacognition",
        "nous.world_model",
        "nous.agents",
        "nous.capabilities",
        "nous.prediction",
        "nous.reasoning",
        "nous.cognitive_arch",
        "nous.grounding",
    ]
    failures = []
    for mod_name in modules:
        try:
            importlib.import_module(mod_name)
        except Exception as e:
            failures.append(f"{mod_name}: {e}")
    assert not failures, "Import failures:\n" + "\n".join(failures)


def test_version_is_7():
    """VERSION file should be 7.0.0."""
    version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
    assert version == "7.0.0", f"Expected 7.0.0, got {version}"


def test_pyproject_name_is_nous():
    """pyproject.toml should have name = 'nous'."""
    content = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "nous"' in content
