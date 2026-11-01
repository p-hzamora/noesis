"""Assembler from a hook plan to the outcome reported to the caller."""

from noesis.bounded_context.capture.application.dtos import AgentHookChangeDto, AgentHookPlanDto


class AgentHookChangeAssembler:
    """`to_dto` turns a plan and what happened to it into the reported outcome."""

    @staticmethod
    def to_dto(plan: AgentHookPlanDto, *, applied: bool, backup: str | None) -> AgentHookChangeDto:
        """The outcome of `plan`; `installed` reflects the file as it is after the operation."""
        return AgentHookChangeDto(
            settings_file=plan.settings_file,
            command=plan.command,
            changed=plan.changed,
            applied=applied,
            backup=backup,
            diff=plan.diff if plan.changed else "",
            installed=plan.installed_after if applied else plan.installed_before,
        )
