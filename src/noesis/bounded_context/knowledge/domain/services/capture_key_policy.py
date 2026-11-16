"""The idempotency keys of a capture: one for the plan, one per step of each candidate."""

from noesis.bounded_context.knowledge.domain.value_objects.curation_plan import FIRST_ORDINAL

STEP_EXPERIENCE: str = "experience"
STEP_KNOWLEDGE: str = "knowledge"
STEP_REVISE: str = "revise"
STEP_SUPERSEDES: str = "supersedes"
STEP_SUPPORTS_PREFIX: str = "supports-"

TICKET_LENGTH: int = 16


class CaptureKeyPolicy:
    """Keys are `capture/<submission_key>/plan` and `capture/<submission_key>/<ordinal>/<step>`.

    A successor uses `knowledge` then `supersedes` under its own ordinal (D-011). A `supports`
    step sits under the knowledge candidate's ordinal and names the experience candidate's
    ordinal. Ordinals start at `FIRST_ORDINAL` (1).
    """

    @staticmethod
    def plan_key(submission_key: str) -> str:
        """The key of the plan registration."""
        return f"capture/{submission_key}/plan"

    @staticmethod
    def step_key(submission_key: str, ordinal: int, step: str) -> str:
        """The key of one step of one candidate."""
        return f"capture/{submission_key}/{ordinal}/{step}"

    @staticmethod
    def supports_step(evidence_ordinal: int) -> str:
        """The step name of the `supports` assertion from the experience at `evidence_ordinal`."""
        return f"{STEP_SUPPORTS_PREFIX}{evidence_ordinal}"

    @staticmethod
    def ticket_of(submission_key: str) -> str:
        """The inbox ticket of a submission: derived, so the lock can be taken before staging."""
        return submission_key[:TICKET_LENGTH]

    @staticmethod
    def first_ordinal() -> int:
        """The ordinal of the first candidate."""
        return FIRST_ORDINAL
