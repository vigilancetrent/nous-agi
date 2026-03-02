"""
Nous — Self-Modifying Cognitive Architecture.

Controlled modification of prompts and context configuration with git versioning.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from nous.utils import get_env
import pathlib
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


@dataclass
class PromptModification:
    """A tracked prompt modification."""
    id: str = ""
    prompt_path: str = ""
    rationale: str = ""
    diff_summary: str = ""
    old_hash: str = ""
    new_hash: str = ""
    timestamp: float = 0.0
    status: str = "proposed"   # "proposed" | "applied" | "rolled_back"
    review_verdict: str = ""   # "approved" | "rejected" | ""


class CognitiveArchitecture:
    """Self-modification of prompts and context with safety controls."""

    def __init__(self, repo_dir: pathlib.Path | None = None,
                 drive_root: pathlib.Path | None = None):
        self._repo_dir = repo_dir or pathlib.Path(get_env("NOUS_REPO_DIR", "."))
        root = drive_root or pathlib.Path(get_env("NOUS_DRIVE_ROOT", str(pathlib.Path.home() / ".nous")))
        self._dir = root / "memory" / "cognitive_arch"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._modifications_path = self._dir / "modifications.jsonl"
        self._config_path = self._dir / "context_config.json"

    def analyze_prompt_effectiveness(self, prompt_path: str) -> Dict[str, Any]:
        """Analyze a prompt file for effectiveness indicators."""
        full_path = self._repo_dir / prompt_path
        if not full_path.exists():
            return {"error": f"Prompt file not found: {prompt_path}"}

        content = full_path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()

        analysis = {
            "path": prompt_path,
            "total_lines": len(lines),
            "total_chars": len(content),
            "sections": [],
            "estimated_tokens": len(content) // 4,
            "has_examples": "example" in content.lower() or "```" in content,
            "has_constraints": any(w in content.lower() for w in ["must", "never", "always", "required"]),
            "has_identity": any(w in content.lower() for w in ["i am", "you are", "identity"]),
            "hash": hashlib.sha256(content.encode()).hexdigest()[:12],
        }

        # Detect sections (markdown headers)
        for i, line in enumerate(lines):
            if line.startswith("#"):
                analysis["sections"].append({
                    "header": line.strip("# ").strip(),
                    "line": i + 1,
                })

        return analysis

    def propose_prompt_modification(self, prompt_path: str, rationale: str,
                                      changes_description: str) -> Dict[str, Any]:
        """Propose a prompt modification (does not apply it)."""
        full_path = self._repo_dir / prompt_path
        if not full_path.exists():
            return {"error": f"Prompt file not found: {prompt_path}"}

        old_content = full_path.read_text(encoding="utf-8")
        old_hash = hashlib.sha256(old_content.encode()).hexdigest()[:12]

        mod = PromptModification(
            id=hashlib.sha256(f"{prompt_path}:{time.time()}".encode()).hexdigest()[:10],
            prompt_path=prompt_path,
            rationale=rationale,
            diff_summary=changes_description,
            old_hash=old_hash,
            timestamp=time.time(),
            status="proposed",
        )

        # Log the proposal
        with open(self._modifications_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(mod), separators=(",", ":")) + "\n")

        return {
            "modification_id": mod.id,
            "status": "proposed",
            "prompt_path": prompt_path,
            "rationale": rationale,
            "note": "Use modify_prompt to apply after review.",
        }

    def apply_prompt_modification(self, modification_id: str,
                                    new_content: str) -> str:
        """Apply a proposed prompt modification."""
        # Find the modification
        mods = self._load_modifications()
        mod = None
        for m in mods:
            if m.id == modification_id:
                mod = m
                break

        if not mod:
            return f"Modification {modification_id} not found."

        full_path = self._repo_dir / mod.prompt_path
        if not full_path.exists():
            return f"Prompt file {mod.prompt_path} not found."

        # Backup old content
        old_content = full_path.read_text(encoding="utf-8")
        backup_path = self._dir / f"backup_{mod.id}_{mod.old_hash}.txt"
        backup_path.write_text(old_content, encoding="utf-8")

        # Apply
        full_path.write_text(new_content, encoding="utf-8")
        new_hash = hashlib.sha256(new_content.encode()).hexdigest()[:12]

        # Update modification record
        mod.status = "applied"
        mod.new_hash = new_hash
        self._update_modification(mod)

        log.info("Applied prompt modification %s to %s", modification_id, mod.prompt_path)
        return f"Applied modification {modification_id}. Backup at {backup_path.name}."

    def modify_context_config(self, changes: Dict[str, Any]) -> str:
        """Modify context building configuration."""
        config = {}
        if self._config_path.exists():
            try:
                config = json.loads(self._config_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                config = {}

        config.update(changes)
        config["last_modified"] = time.time()

        self._config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        return f"Context config updated: {list(changes.keys())}"

    def get_context_config(self) -> Dict[str, Any]:
        """Get current context configuration."""
        if self._config_path.exists():
            try:
                return json.loads(self._config_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        return {}

    def rollback_modification(self, modification_id: str) -> str:
        """Rollback a previously applied modification."""
        mods = self._load_modifications()
        mod = None
        for m in mods:
            if m.id == modification_id:
                mod = m
                break

        if not mod:
            return f"Modification {modification_id} not found."
        if mod.status != "applied":
            return f"Modification {modification_id} not in applied state (current: {mod.status})."

        backup_path = self._dir / f"backup_{mod.id}_{mod.old_hash}.txt"
        if not backup_path.exists():
            return f"Backup not found for modification {modification_id}."

        full_path = self._repo_dir / mod.prompt_path
        backup_content = backup_path.read_text(encoding="utf-8")
        full_path.write_text(backup_content, encoding="utf-8")

        mod.status = "rolled_back"
        self._update_modification(mod)

        log.info("Rolled back modification %s", modification_id)
        return f"Rolled back modification {modification_id} on {mod.prompt_path}."

    def _load_modifications(self) -> List[PromptModification]:
        mods = []
        if self._modifications_path.exists():
            for line in self._modifications_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    mods.append(PromptModification(**{
                        k: v for k, v in data.items()
                        if k in PromptModification.__dataclass_fields__
                    }))
                except (json.JSONDecodeError, TypeError):
                    continue
        return mods

    def _update_modification(self, mod: PromptModification) -> None:
        """Rewrite modifications file with updated entry."""
        mods = self._load_modifications()
        for i, m in enumerate(mods):
            if m.id == mod.id:
                mods[i] = mod
                break
        with open(self._modifications_path, "w", encoding="utf-8") as f:
            for m in mods:
                f.write(json.dumps(asdict(m), separators=(",", ":")) + "\n")
