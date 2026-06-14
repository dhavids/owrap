import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from owrap.utils.donow import (
    _counters_path,
    _read_counters,
    _write_counters,
    _get_area_section_text,
    _hash_area_section,
    _count_marked_steps,
    check_donow,
)
from owrap.constants import (
    NO_CONTEXT_MSG,
    NO_AREA_SECTION_MSG,
    CTX_DUE_MSG,
    UPDR_DUE_MSG,
)


class TestCounters:
    def test_counters_path(self):
        p = _counters_path("abc123")
        assert p.name == "abc123.counters.json"
        assert "sessions" in str(p)

    def test_read_write_counters(self, tmp_path):
        with patch("owrap.utils.donow.COUNTERS_DIR", tmp_path):
            sid = "test_sid"
            data = {"orun_count": 3, "plan_count": 1}
            _write_counters(sid, data)
            result = _read_counters(sid)
            assert result == data

    def test_read_counters_missing_returns_empty(self, tmp_path):
        with patch("owrap.utils.donow.COUNTERS_DIR", tmp_path):
            result = _read_counters("nonexistent")
            assert result == {}

    def test_read_counters_corrupt(self, tmp_path):
        with patch("owrap.utils.donow.COUNTERS_DIR", tmp_path):
            _counters_path("bad").write_text("not json")
            result = _read_counters("bad")
            assert result == {}


class TestAreaSection:
    def test_hash_empty_for_missing_file(self):
        h = _hash_area_section(Path("/nonexistent/file.md"), "test")
        assert h == ""

    def test_get_section_text_present(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("## Intro\nhello\n\n## MyArea\ndata here\nmore data\n\n## Next\nbye\n")
        text = _get_area_section_text(f, "MyArea")
        assert "data here" in text
        assert "more data" in text
        assert "Next" not in text
        assert "bye" not in text

    def test_get_section_text_absent(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("## Intro\nhello\n\n## Other\nbye\n")
        text = _get_area_section_text(f, "Missing")
        assert text == ""

    def test_hash_stable(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("## A\nhello world\n\n## B\ntest\n")
        h1 = _hash_area_section(f, "A")
        h2 = _hash_area_section(f, "A")
        assert h1 == h2
        assert len(h1) == 64

    def test_hash_differs_on_change(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("## A\nhello world\n")
        h1 = _hash_area_section(f, "A")
        f.write_text("## A\nhello world changed\n")
        h2 = _hash_area_section(f, "A")
        assert h1 != h2


class TestCountMarkedSteps:
    def test_empty_plan(self, tmp_path):
        p = tmp_path / "plan.md"
        p.write_text("## [ACTIVE] 1 — test\n")
        assert _count_marked_steps(p) == 0

    def test_counts_marked_only_in_active(self, tmp_path):
        p = tmp_path / "plan.md"
        p.write_text(
            "## [ACTIVE] 1 — test\n"
            "1. [x] Step one\n"
            "2. [ ] Step two\n"
            "3. [x] Step three\n"
            "\n"
            "## [PAUSED] 2 — other\n"
            "1. [x] Step four (should not count)\n"
        )
        assert _count_marked_steps(p) == 2

    def test_no_active_block(self, tmp_path):
        p = tmp_path / "plan.md"
        p.write_text("## Some section\n1. [x] not active\n")
        assert _count_marked_steps(p) == 0

    def test_marks_in_next_section_not_counted(self, tmp_path):
        p = tmp_path / "plan.md"
        p.write_text(
            "## [ACTIVE] 1 — test\n"
            "1. [x] counted\n"
            "## Next\n"
            "1. [x] not counted\n"
        )
        assert _count_marked_steps(p) == 1

    def test_missing_file(self):
        assert _count_marked_steps(Path("/nonexistent/plan.md")) == 0


class TestCheckDonow:
    @pytest.fixture
    def setup_env(self, tmp_path):
        """Set up a realistic environment for check_donow testing."""
        sessions_dir = tmp_path / "sessions"
        counters_dir = tmp_path / "counters"
        context_dir = tmp_path / "context"
        plans_dir = tmp_path / "plans"
        research_dir = tmp_path / "research"

        for d in [sessions_dir, context_dir, plans_dir, research_dir, counters_dir]:
            d.mkdir(parents=True, exist_ok=True)

        research_dir.joinpath("memory").mkdir(parents=True, exist_ok=True)
        research_dir.joinpath("projects").mkdir(parents=True, exist_ok=True)

        return {
            "sessions": sessions_dir,
            "counters": counters_dir,
            "context": context_dir,
            "plans": plans_dir,
            "research": research_dir,
        }

    def _make_mocks(self, setup_env, sid="test123", area="myarea", research="testr"):
        """Create mocks with the right path patches."""
        env = setup_env
        cp = env["context"] / f"context_{sid}.md"
        plan = env["plans"] / f"plan_{sid}.md"
        memory = env["research"] / "memory" / f"{research}.md"
        projects = env["research"] / "projects" / f"{research}.md"

        # Create files
        cp.write_text("## Focus\nstarted\n\n## Active Plan\n1. [x] done\n2. [ ] todo\n\n## Key Locations\n\n")
        plan.write_text(
            "## [ACTIVE] 1 — test\n"
            "1. [x] Step one\n"
            "2. [ ] Step two\n"
            "3. [ ] Step three\n"
        )
        memory.write_text(f"## {area}\nmemory content here\n\n## Other\nstuff\n")
        projects.write_text(f"## {area}\nproject content here\n\n## Other\nstuff\n")

        manager = MagicMock()
        manager.session_id = sid
        manager.research = research

        def _ctx_path(s):
            return env["context"] / f"context_{s}.md"

        def _plan_path(s):
            return env["plans"] / f"plan_{s}.md"

        def _config():
            return {
                "research_root": str(env["research"]),
                "ctx_update_every_orun": 3,
                "updr_every_plans": 2,
                "updr_every_steps": 15,
            }

        return env, manager, cp, plan, memory, projects, _ctx_path, _plan_path, _config

    def test_no_area_returns_none(self, setup_env):
        env, manager, cp, plan, memory, projects, ctx_path_fn, plan_path_fn, config_fn = self._make_mocks(setup_env)
        with patch("owrap.utils.donow.context_path", ctx_path_fn), \
             patch("owrap.utils.donow.get_plan_path", plan_path_fn), \
             patch("owrap.utils.donow._read_config", config_fn), \
             patch("owrap.utils.donow.COUNTERS_DIR", env["counters"]):
            result = check_donow(manager, "test123", "", "testr", "task")
            assert result is None

    def test_missing_context_file(self, setup_env):
        env, manager, cp, plan, memory, projects, ctx_path_fn, plan_path_fn, config_fn = self._make_mocks(setup_env)
        sid = "test123"
        # Delete context file
        cp.unlink()
        with patch("owrap.utils.donow.context_path", ctx_path_fn), \
             patch("owrap.utils.donow.get_plan_path", plan_path_fn), \
             patch("owrap.utils.donow._read_config", config_fn), \
             patch("owrap.utils.donow.COUNTERS_DIR", env["counters"]):
            result = check_donow(manager, sid, "myarea", "testr", "task")
            assert result is not None
            assert "#DO NOW" in result
            assert "Context file missing" in result
            assert "Context Recovery" in result

    def test_missing_area_section(self, setup_env):
        env, manager, cp, plan, memory, projects, ctx_path_fn, plan_path_fn, config_fn = self._make_mocks(setup_env)
        sid = "test123"
        # Remove area section from memory
        memory.write_text("## Other\nno myarea section\n")
        with patch("owrap.utils.donow.context_path", ctx_path_fn), \
             patch("owrap.utils.donow.get_plan_path", plan_path_fn), \
             patch("owrap.utils.donow._read_config", config_fn), \
             patch("owrap.utils.donow.COUNTERS_DIR", env["counters"]):
            result = check_donow(manager, sid, "myarea", "testr", "task")
            assert result is not None
            assert "#DO NOW" in result
            assert "myarea" in result
            assert "missing in memory/projects" in result

    def test_orun_count_triggers_context_update(self, setup_env):
        env, manager, cp, plan, memory, projects, ctx_path_fn, plan_path_fn, config_fn = self._make_mocks(setup_env)
        sid = "test123"

        with patch("owrap.utils.donow.context_path", ctx_path_fn), \
             patch("owrap.utils.donow.get_plan_path", plan_path_fn), \
             patch("owrap.utils.donow._read_config", config_fn), \
             patch("owrap.utils.donow.COUNTERS_DIR", env["counters"]):
            # First two task calls should not trigger (need >= 3)
            result1 = check_donow(manager, sid, "myarea", "testr", "task")
            assert result1 is None

            result2 = check_donow(manager, sid, "myarea", "testr", "task")
            assert result2 is None

            # Third should trigger
            result3 = check_donow(manager, sid, "myarea", "testr", "task")
            assert result3 is not None
            assert "#DO NOW" in result3
            assert "Context update due" in result3
            assert "orun=3/3" in result3

    def test_plan_count_triggers_updr(self, setup_env):
        env, manager, cp, plan, memory, projects, ctx_path_fn, plan_path_fn, config_fn = self._make_mocks(setup_env)
        sid = "test123"

        with patch("owrap.utils.donow.context_path", ctx_path_fn), \
             patch("owrap.utils.donow.get_plan_path", plan_path_fn), \
             patch("owrap.utils.donow._read_config", config_fn), \
             patch("owrap.utils.donow.COUNTERS_DIR", env["counters"]):
            # First exec should not trigger (need >= 2)
            result1 = check_donow(manager, sid, "myarea", "testr", "exec")
            assert result1 is None

            # Second should trigger both ctx and updr (plan_count >= 2)
            result2 = check_donow(manager, sid, "myarea", "testr", "exec")
            assert result2 is not None
            assert "Context update due" in result2
            assert "Update protocol due" in result2

    def test_mtime_reset_clears_orun(self, setup_env):
        env, manager, cp, plan, memory, projects, ctx_path_fn, plan_path_fn, config_fn = self._make_mocks(setup_env)
        sid = "test123"

        with patch("owrap.utils.donow.context_path", ctx_path_fn), \
             patch("owrap.utils.donow.get_plan_path", plan_path_fn), \
             patch("owrap.utils.donow._read_config", config_fn), \
             patch("owrap.utils.donow.COUNTERS_DIR", env["counters"]):
            # Trigger ctx update, which records ctx_mtime_at_injection
            for _ in range(3):
                check_donow(manager, sid, "myarea", "testr", "task")

            counters = _read_counters(sid)
            assert counters["orun_count"] == 3
            assert "ctx_mtime_at_injection" in counters

            # Simulate context being updated (touch the file)
            time.sleep(0.01)
            cp.write_text(cp.read_text() + "\n")  # Change mtime

            # Next task call should reset orun_count
            result = check_donow(manager, sid, "myarea", "testr", "task")
            counters2 = _read_counters(sid)
            assert counters2["orun_count"] == 1  # Reset to 0 then incremented to 1

    def test_hash_reset_clears_plan_count(self, setup_env):
        env, manager, cp, plan, memory, projects, ctx_path_fn, plan_path_fn, config_fn = self._make_mocks(setup_env)
        sid = "test123"

        with patch("owrap.utils.donow.context_path", ctx_path_fn), \
             patch("owrap.utils.donow.get_plan_path", plan_path_fn), \
             patch("owrap.utils.donow._read_config", config_fn), \
             patch("owrap.utils.donow.COUNTERS_DIR", env["counters"]):
            # Trigger updr (plan_count >= 2), which records area_hash
            for _ in range(2):
                check_donow(manager, sid, "myarea", "testr", "exec")

            counters = _read_counters(sid)
            assert counters["plan_count"] == 2
            assert "area_hash" in counters
            assert "myarea" in counters["area_hash"]

            # Simulate area being updated (change memory content)
            memory.write_text("## myarea\nupdated memory content\n\n## Other\nstuff\n")

            # Next exec should reset plan_count
            result = check_donow(manager, sid, "myarea", "testr", "exec")
            counters2 = _read_counters(sid)
            assert counters2["plan_count"] == 1  # Reset to 0 then incremented to 1

    def test_marked_steps_triggers_when_baseline_diff(self, setup_env):
        env, manager, cp, plan, memory, projects, ctx_path_fn, plan_path_fn, config_fn = self._make_mocks(setup_env)
        sid = "test123"

        # Modify config to make steps threshold very low
        def config_low_steps():
            return {
                "research_root": str(env["research"]),
                "ctx_update_every_orun": 100,
                "updr_every_plans": 100,
                "updr_every_steps": 1,
            }

        plan.write_text(
            "## [ACTIVE] 1 — test\n"
            "1. [x] Step one (done)\n"
            "2. [ ] Step two\n"
        )

        with patch("owrap.utils.donow.context_path", ctx_path_fn), \
             patch("owrap.utils.donow.get_plan_path", plan_path_fn), \
             patch("owrap.utils.donow._read_config", config_low_steps), \
             patch("owrap.utils.donow.COUNTERS_DIR", env["counters"]):
            # The baseline is set on first run when counters are empty (marked_steps_baseline=0)
            # Plan has 1 marked step, threshold is 1, so marked_steps=1 >= 1 → triggers
            result = check_donow(manager, sid, "myarea", "testr", "task")
            assert result is not None
            assert "steps=1/1" in result


class TestCapContextSections:
    def test_active_plan_capped_to_5_lines(self, tmp_path):
        from owrap.manager import Manager

        manager = Manager.__new__(Manager)
        cp = tmp_path / "context.md"
        cp.write_text(
            "## Active Plan\n"
            "1. [x] line one\n"
            "2. [x] line two\n"
            "3. [x] line three\n"
            "4. [ ] line four\n"
            "5. [ ] line five\n"
            "6. [ ] line six\n"
            "7. [ ] line seven\n"
            "\n"
            "## Decisions\n"
            "A decision\n"
        )
        manager._cap_context_sections(cp)
        content = cp.read_text()
        # Should only have 5 content lines under ## Active Plan
        active_lines = [l for l in content.splitlines() if l.startswith(("## Active Plan", "1.", "2.", "3.", "4.", "5.", "6.", "7."))]
        assert len(active_lines) <= 6  # 1 header + 5 content max
        assert "6. [ ] line six" not in content
        assert "7. [ ] line seven" not in content

    def test_active_plan_empty_stays_empty(self, tmp_path):
        from owrap.manager import Manager

        manager = Manager.__new__(Manager)
        cp = tmp_path / "context.md"
        cp.write_text("## Active Plan\n\n## Decisions\nsome decision\n")
        manager._cap_context_sections(cp)
        content = cp.read_text()
        assert "## Active Plan" in content
        assert "## Decisions" in content

    def test_active_plan_with_3_steps_preserved(self, tmp_path):
        from owrap.manager import Manager

        manager = Manager.__new__(Manager)
        cp = tmp_path / "context.md"
        cp.write_text(
            "## Active Plan\n"
            "1. [ ] step one\n"
            "2. [ ] step two\n"
            "3. [ ] step three\n"
            "\n"
            "## Decisions\n"
            "decision\n"
        )
        manager._cap_context_sections(cp)
        content = cp.read_text()
        assert "step one" in content
        assert "step two" in content
        assert "step three" in content


def test_sync_task_excluded_from_count(tmp_path):
    from owrap.utils.donow import check_donow, _counters_path
    from unittest.mock import MagicMock
    manager = MagicMock()
    sid = "testsid"
    counters_dir = tmp_path / "sessions"
    counters_dir.mkdir()
    import owrap.utils.donow as donow_mod
    monkeypatch_attr = {"COUNTERS_DIR": counters_dir}

    input_path = tmp_path / "sync_task_marl.md"
    input_path.write_text("# Sync task\nsome content\n")

    ctx_file = tmp_path / "context.md"
    ctx_file.write_text("## Focus\n\n## Key Locations\n\n## Decisions\n\n## Environment\n")

    import json
    (counters_dir / f"{sid}.counters.json").write_text(json.dumps({"orun_count": 0}))

    orig_counters = donow_mod.COUNTERS_DIR
    orig_ctx = donow_mod.context_path
    orig_config = donow_mod._read_config
    orig_plan = donow_mod.get_plan_path
    try:
        donow_mod.COUNTERS_DIR = counters_dir
        donow_mod.context_path = lambda sid: ctx_file
        donow_mod._read_config = lambda: {"ctx_update_every_orun": 3, "updr_every_plans": 2, "updr_every_steps": 15}
        donow_mod.get_plan_path = lambda sid: tmp_path / "plan.md"
        check_donow(manager, sid, "main", "myresearch", kind="task", input_path=input_path)
        data = json.loads((counters_dir / f"{sid}.counters.json").read_text())
        assert data.get("orun_count", 0) == 0, "sync_task should not increment orun_count"
    finally:
        donow_mod.COUNTERS_DIR = orig_counters
        donow_mod.context_path = orig_ctx
        donow_mod._read_config = orig_config
        donow_mod.get_plan_path = orig_plan


def test_context_update_resets_count(tmp_path):
    from owrap.utils.donow import check_donow, _counters_path
    from unittest.mock import MagicMock
    import json
    manager = MagicMock()
    sid = "testsid2"
    counters_dir = tmp_path / "sessions"
    counters_dir.mkdir()

    input_path = tmp_path / "input_ctx.md"
    input_path.write_text("# Context Update\n\nsome update content\n")

    ctx_file = tmp_path / "context.md"
    ctx_file.write_text("## Focus\n\n## Key Locations\n\n## Decisions\n\n## Environment\n")

    (counters_dir / f"{sid}.counters.json").write_text(json.dumps({"orun_count": 2}))

    import owrap.utils.donow as donow_mod
    orig_counters = donow_mod.COUNTERS_DIR
    orig_ctx = donow_mod.context_path
    orig_config = donow_mod._read_config
    orig_plan = donow_mod.get_plan_path
    try:
        donow_mod.COUNTERS_DIR = counters_dir
        donow_mod.context_path = lambda sid: ctx_file
        donow_mod._read_config = lambda: {"ctx_update_every_orun": 3, "updr_every_plans": 2, "updr_every_steps": 15}
        donow_mod.get_plan_path = lambda sid: tmp_path / "plan.md"
        check_donow(manager, sid, "main", "myresearch", kind="task", input_path=input_path)
        data = json.loads((counters_dir / f"{sid}.counters.json").read_text())
        assert data.get("orun_count", 0) == 0, "context update should reset orun_count to 0"
    finally:
        donow_mod.COUNTERS_DIR = orig_counters
        donow_mod.context_path = orig_ctx
        donow_mod._read_config = orig_config
        donow_mod.get_plan_path = orig_plan
