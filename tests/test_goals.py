"""Test goal tree operations."""

import pathlib
import tempfile
import pytest


def test_goal_create_and_list():
    """Create goals and list them."""
    from nous.goals import GoalTree, Goal

    with tempfile.TemporaryDirectory() as tmp:
        tree = GoalTree(drive_root=pathlib.Path(tmp))

        gid = tree.add_goal(Goal(
            title="Learn Rust",
            description="Pick up Rust for systems programming",
            priority=3,
        ))
        assert gid

        active = tree.get_active_goals()
        assert len(active) == 1
        assert active[0].title == "Learn Rust"


def test_goal_hierarchy():
    """Sub-goals should be linked to parents."""
    from nous.goals import GoalTree, Goal

    with tempfile.TemporaryDirectory() as tmp:
        tree = GoalTree(drive_root=pathlib.Path(tmp))

        parent_id = tree.add_goal(Goal(title="Master ML", priority=2))
        child_id = tree.add_goal(Goal(
            title="Complete PyTorch tutorial",
            parent_id=parent_id,
            priority=4,
        ))

        children = tree.get_children(parent_id)
        assert len(children) == 1
        assert children[0].title == "Complete PyTorch tutorial"


def test_goal_update():
    """Update goal progress and status."""
    from nous.goals import GoalTree, Goal

    with tempfile.TemporaryDirectory() as tmp:
        tree = GoalTree(drive_root=pathlib.Path(tmp))
        gid = tree.add_goal(Goal(title="Test goal"))

        updated = tree.update_goal(gid, progress=0.5, status="active")
        assert updated.progress == 0.5

        completed = tree.update_goal(gid, status="completed")
        assert completed.status == "completed"


def test_goal_tree_formatting():
    """Goal tree should produce readable output."""
    from nous.goals import GoalTree, Goal

    with tempfile.TemporaryDirectory() as tmp:
        tree = GoalTree(drive_root=pathlib.Path(tmp))
        tree.add_goal(Goal(title="Build AGI", priority=1, progress=0.3))

        output = tree.get_goal_tree()
        assert "Build AGI" in output
        assert "30%" in output


def test_goal_pruning():
    """Stale goals should be pruned."""
    from nous.goals import GoalTree, Goal
    import time

    with tempfile.TemporaryDirectory() as tmp:
        tree = GoalTree(drive_root=pathlib.Path(tmp))
        gid = tree.add_goal(Goal(title="Old goal"))

        # Manually set updated_at to past
        tree._goals[gid].updated_at = time.time() - 999999
        tree._save()

        pruned = tree.prune_stale_goals(max_age_hours=1)
        assert gid in pruned
