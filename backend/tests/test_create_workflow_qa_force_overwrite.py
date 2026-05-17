"""桩：create_workflow 工具对 final-QA 任务 detail 字段的强制覆盖。

Why this spec exists
--------------------
CreateWorkflowTool runs `_normalize_tasks` over Plan Maker's draft
which (a) appends a final QA + debugger pair when missing, and (b)
**overwrites** the final-QA task's `detail` with the canonical
QA_TASK_DETAIL string regardless of what the planner wrote.

The "last lock" the user called out: planners (LLM) sometimes
hallucinate a more permissive QA brief that lets faulty deliverables
pass silently — see the silent-pass loophole fixed in 546dfd3. We
*always* clobber the QA task's detail with the canonical text so the
QA agent's grounding prompt is deterministic.

The existing test_create_workflow_tool.py covers most of this
indirectly via `TestNormalize::test_existing_debugger_keeps_canonical_detail_and_dep`,
but the QA-specific clobber semantic isn't named explicitly anywhere
and tends to regress when someone "refactors" the normalize step.

This file pins the contract by name. Stubs only — flip xfail off when
implemented.
"""
from __future__ import annotations

import pytest

# from src.tools.builtin.local.create_workflow import (
#     QA_TASK_DETAIL,
#     _normalize_tasks,
# )

TODO = pytest.mark.xfail(reason="todo: stub for QA detail clobber", strict=False)


class TestFinalQaDetailIsClobbered:
    @TODO
    def test_planner_supplied_qa_detail_is_overwritten(self):
        """Input task list includes a final-QA task whose detail is some
        permissive string; after _normalize_tasks that detail MUST be
        replaced with QA_TASK_DETAIL verbatim."""
        raise NotImplementedError

    @TODO
    def test_appended_qa_uses_canonical_detail(self):
        """When the planner omits a final QA, _normalize_tasks appends
        one — verify the appended task's detail is QA_TASK_DETAIL, not
        an empty string or a synthesised one."""
        raise NotImplementedError

    @TODO
    def test_clobber_runs_even_when_other_fields_are_fine(self):
        """Edge case: planner provides a final QA with a sensible title
        and correct deps, only the detail is off. Normalize should still
        overwrite the detail (no smart-merge)."""
        raise NotImplementedError


class TestClobberDoesNotAffectNonFinalQa:
    @TODO
    def test_mid_pipeline_qa_task_detail_untouched(self):
        """If a planner inserts a per-stage QA somewhere in the middle
        (kind != 'final_qa'), its detail must NOT be clobbered — only
        the FINAL QA gets the canonical override."""
        raise NotImplementedError


class TestDebuggerPairing:
    @TODO
    def test_debugger_dep_points_at_final_qa(self):
        """The auto-appended debugger task should depend on the final
        QA, and its own detail should remain the canonical debugger
        text (this is the second half of the "last lock")."""
        raise NotImplementedError
