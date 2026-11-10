import pytest
from pydantic import ValidationError

from tensordata.schemas import ActorProvenance


def test_agent_actor_requires_accountable_human_and_tool():
    with pytest.raises(ValidationError):
        ActorProvenance(
            actor_type="agent",
            actor_id="agent-01",
            tool_name="Claude Code",
        )


def test_agent_actor_accepts_complete_attribution():
    actor = ActorProvenance(
        actor_type="agent",
        actor_id="agent-01",
        role="producer",
        tool_name="Claude Code",
        tool_version="1.0",
        model_id="model-x",
        run_id="run-123",
        work_package="WP-7",
        accountable_human="project-maintainer",
        reviewer_agent_ids=["reviewer-02"],
        verification_refs=["https://example.invalid/ci/123"],
    )
    assert actor.actor_type == "agent"
    assert actor.accountable_human == "project-maintainer"
    assert actor.reviewer_agent_ids == ["reviewer-02"]


def test_non_agent_actor_does_not_require_agent_fields():
    actor = ActorProvenance(actor_type="system", actor_id="ci-runner")
    assert actor.actor_type == "system"


def test_unknown_actor_is_explicit():
    actor = ActorProvenance()
    assert actor.actor_type == "unknown"
