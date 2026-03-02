"""
Nous — World Model.

AST-based dependency analysis and impact prediction for the codebase.
"""

from __future__ import annotations

import ast
import json
import logging
import os
from nous.utils import get_env
import pathlib
import time
from typing import Any, Dict, List, Optional, Set

log = logging.getLogger(__name__)


class WorldModel:
    """Codebase dependency graph and impact prediction."""

    def __init__(self, repo_dir: pathlib.Path | None = None,
                 drive_root: pathlib.Path | None = None):
        self._repo_dir = repo_dir or pathlib.Path(get_env("NOUS_REPO_DIR", "."))
        root = drive_root or pathlib.Path(get_env("NOUS_DRIVE_ROOT", str(pathlib.Path.home() / ".nous")))
        self._cache_path = root / "memory" / "world_model.json"
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._graph: Dict[str, Dict[str, Any]] = {}
        self._load_cache()

    def _load_cache(self) -> None:
        if self._cache_path.exists():
            try:
                self._graph = json.loads(self._cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, TypeError):
                self._graph = {}

    def _save_cache(self) -> None:
        self._cache_path.write_text(json.dumps(self._graph, indent=2), encoding="utf-8")

    def build_dependency_graph(self) -> Dict[str, Any]:
        """Build import and call dependency graph from AST analysis."""
        self._graph = {}
        py_files = list(self._repo_dir.rglob("*.py"))

        for py_file in py_files:
            try:
                rel = str(py_file.relative_to(self._repo_dir))
                if "__pycache__" in rel:
                    continue
                source = py_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source, filename=rel)

                imports = []
                functions = []
                classes = []

                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imports.append(alias.name)
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            imports.append(node.module)
                    elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                        functions.append({
                            "name": node.name,
                            "lineno": node.lineno,
                            "lines": (node.end_lineno or node.lineno) - node.lineno + 1,
                        })
                    elif isinstance(node, ast.ClassDef):
                        classes.append({
                            "name": node.name,
                            "lineno": node.lineno,
                        })

                self._graph[rel] = {
                    "imports": imports,
                    "functions": functions,
                    "classes": classes,
                    "lines": len(source.splitlines()),
                    "analyzed_at": time.time(),
                }
            except (SyntaxError, UnicodeDecodeError) as e:
                log.debug("Skip %s: %s", py_file, e)
                continue

        self._save_cache()
        log.info("World model built: %d modules", len(self._graph))
        return {
            "modules": len(self._graph),
            "total_functions": sum(len(m["functions"]) for m in self._graph.values()),
            "total_classes": sum(len(m["classes"]) for m in self._graph.values()),
        }

    def predict_impact(self, changed_files: List[str]) -> List[str]:
        """Predict which files may be affected by changes to the given files."""
        if not self._graph:
            self.build_dependency_graph()

        affected: Set[str] = set(changed_files)

        # Build reverse dependency map
        reverse_deps: Dict[str, Set[str]] = {}
        for module, info in self._graph.items():
            for imp in info.get("imports", []):
                # Convert import to possible file paths
                imp_path = imp.replace(".", "/") + ".py"
                imp_pkg = imp.replace(".", "/") + "/__init__.py"
                for target in [imp_path, imp_pkg]:
                    if target not in reverse_deps:
                        reverse_deps[target] = set()
                    reverse_deps[target].add(module)

        # BFS to find transitively affected files
        queue = list(changed_files)
        visited = set()
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            affected.add(current)
            for dep_file in reverse_deps.get(current, set()):
                if dep_file not in visited:
                    queue.append(dep_file)

        return sorted(affected)

    def get_module_context(self, module_path: str) -> str:
        """Get context summary for a module."""
        info = self._graph.get(module_path)
        if not info:
            return f"Module {module_path} not in world model. Run rebuild_world_model first."

        lines = [f"## {module_path} ({info['lines']} lines)\n"]

        if info["imports"]:
            lines.append(f"**Imports:** {', '.join(info['imports'][:20])}")

        if info["classes"]:
            lines.append("**Classes:**")
            for cls in info["classes"]:
                lines.append(f"  - {cls['name']} (line {cls['lineno']})")

        if info["functions"]:
            lines.append("**Functions:**")
            for fn in info["functions"][:20]:
                lines.append(f"  - {fn['name']}() [{fn['lines']} lines] (line {fn['lineno']})")

        return "\n".join(lines)

    def update_from_observation(self, file_path: str) -> None:
        """Rebuild model for a single file after change."""
        full_path = self._repo_dir / file_path
        if not full_path.exists():
            self._graph.pop(file_path, None)
            self._save_cache()
            return

        try:
            source = full_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=file_path)
            imports = []
            functions = []
            classes = []

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions.append({"name": node.name, "lineno": node.lineno,
                                      "lines": (node.end_lineno or node.lineno) - node.lineno + 1})
                elif isinstance(node, ast.ClassDef):
                    classes.append({"name": node.name, "lineno": node.lineno})

            self._graph[file_path] = {
                "imports": imports, "functions": functions, "classes": classes,
                "lines": len(source.splitlines()), "analyzed_at": time.time(),
            }
            self._save_cache()
        except (SyntaxError, UnicodeDecodeError):
            pass

    def get_summary(self) -> Dict[str, Any]:
        """Get world model summary stats."""
        if not self._graph:
            return {"status": "empty", "hint": "Run rebuild_world_model to populate"}
        return {
            "modules": len(self._graph),
            "total_lines": sum(m["lines"] for m in self._graph.values()),
            "total_functions": sum(len(m["functions"]) for m in self._graph.values()),
            "total_classes": sum(len(m["classes"]) for m in self._graph.values()),
            "largest_modules": sorted(
                [(k, v["lines"]) for k, v in self._graph.items()],
                key=lambda x: -x[1]
            )[:5],
        }
