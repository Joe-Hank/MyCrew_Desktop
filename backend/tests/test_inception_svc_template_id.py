"""桩：InceptionService.template_id 相关行为的契约性测试。

This spec exists because `template_id` was added late in Phase 12 to
pre-bake the template pick (frontend's drawer-initial ChoicePanel) so
the user doesn't have to confirm a template a second time inside the
session. The behaviour is spread across three entry points and is
easy to break in subtle ways:

  - create_session(template_id=...)          → validates & stores it
  - apply_choice(template_id=...)            → late-binding update
  - create_session(parent_project_id=...)    → inherits parent's template

Bigger picture: when mode=="create" the workflow scheduler refuses to
proceed without a session.template_id (see inception_svc.py ~line 850),
so any regression here silently bricks "新建项目" entry.

Each `it` below is currently `xfail(strict=False)` — implement and flip
to a real assertion. Don't delete the xfail until you've actually
exercised the path through `inception_svc.create_session` /
`apply_choice` with real fixtures.
"""
from __future__ import annotations

import pytest

# from unittest.mock import patch
# from services.inception_svc import InceptionService
# from tests.conftest import FakeCRUD, FakeLlmGateway, FakeWSManager


# Shared "todo" marker — kept as a constant so future cleanup is grep-able
TODO = pytest.mark.xfail(reason="todo: implement template_id stub", strict=False)


class TestCreateSessionWithTemplateId:
    @TODO
    async def test_accepts_known_template_id(self):
        """create_session(template_id='unity_2d_urp') should store it
        on the session row verbatim."""
        raise NotImplementedError

    @TODO
    async def test_rejects_unknown_template_id_silently(self):
        """Per current code, unknown template_id is dropped (not raised)
        in create_session — verify the contract. Apply_choice DOES raise;
        the asymmetry is intentional but worth pinning."""
        raise NotImplementedError

    @TODO
    async def test_none_template_id_leaves_field_empty(self):
        raise NotImplementedError


class TestIterateModeInheritsTemplate:
    @TODO
    async def test_iterate_mode_copies_parent_template_id(self):
        """When mode='iterate' + parent_project_id provided, the new
        session should inherit parent.template_id without the caller
        passing it again."""
        raise NotImplementedError

    @TODO
    async def test_iterate_with_explicit_template_id_overrides_parent(self):
        """Caller-provided template_id wins over parent inheritance."""
        raise NotImplementedError

    @TODO
    async def test_iterate_external_mode_does_not_inherit(self):
        """mode='iterate_external' is the "外部已有项目" entry — it gets
        a root_path but should NOT auto-inherit a template."""
        raise NotImplementedError


class TestApplyChoiceTemplateId:
    @TODO
    async def test_apply_choice_sets_template_id(self):
        """POST /sessions/{id}/choices with {template_id: ...} should
        late-bind onto a session that started without one."""
        raise NotImplementedError

    @TODO
    async def test_apply_choice_unknown_template_raises_value_error(self):
        """Unlike create_session, apply_choice DOES raise. Route layer
        translates ValueError → {ok:false, code:'invalid_choice'}."""
        raise NotImplementedError


class TestWorkflowGateOnTemplateId:
    @TODO
    async def test_create_mode_workflow_requires_template_id(self):
        """The scheduler refuses to start a 'create'-mode session that
        never picked a template (inception_svc.py ~line 850). If this
        gate breaks, the user can submit half-baked sessions."""
        raise NotImplementedError
