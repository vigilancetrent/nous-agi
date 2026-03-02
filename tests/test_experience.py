"""Test experience store CRUD and search."""

import pathlib
import tempfile
import pytest


def test_experience_record_and_search():
    """Record an experience and search for it."""
    from nous.experience import ExperienceStore, Experience

    with tempfile.TemporaryDirectory() as tmp:
        store = ExperienceStore(drive_root=pathlib.Path(tmp))

        exp = Experience(
            task_description="Fixed a bug in the login flow",
            task_type="debug",
            approach="Traced the error through logs, found null pointer",
            outcome="success",
            lessons_learned="Always check for null before accessing nested properties",
            domain="code",
        )
        exp_id = store.record(exp)
        assert exp_id

        # Search should find it
        results = store.search("login bug fix", top_k=5)
        assert len(results) >= 1
        assert results[0].task_description == "Fixed a bug in the login flow"


def test_experience_stats():
    """Stats should reflect recorded experiences."""
    from nous.experience import ExperienceStore, Experience

    with tempfile.TemporaryDirectory() as tmp:
        store = ExperienceStore(drive_root=pathlib.Path(tmp))

        for outcome in ["success", "success", "failure"]:
            store.record(Experience(
                task_description=f"Task with {outcome}",
                outcome=outcome,
                domain="code",
            ))

        stats = store.get_stats()
        assert stats["total"] == 3
        assert stats["outcomes"]["success"] == 2
        assert stats["outcomes"]["failure"] == 1


def test_experience_cross_domain():
    """Cross-domain strategy extraction."""
    from nous.experience import ExperienceStore, Experience

    with tempfile.TemporaryDirectory() as tmp:
        store = ExperienceStore(drive_root=pathlib.Path(tmp))
        store.record(Experience(
            task_description="Optimized database queries",
            outcome="success",
            domain="code",
            lessons_learned="Use batch queries instead of N+1",
        ))

        strategies = store.extract_cross_domain_strategies("code", "research")
        assert len(strategies) >= 1
        assert "batch queries" in strategies[0].lower()
