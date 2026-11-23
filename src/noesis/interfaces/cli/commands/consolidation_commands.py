"""`noesis consolidation`: find overlapping accepted knowledge and propose one successor for it.

Check order: usage errors (exit 2, no I/O); user presence when the user applies a decision (the
terminal check, before any store access); store access; the rest is the handlers'. Without
`--yes` (or with `--dry-run`) a command runs every check and writes nothing. Nothing is deleted,
no original or link changes, and a failed step is reported as an error, never as success.
"""

import asyncio
import sys
from typing import Annotated

import typer

from noesis.bounded_context.knowledge.application.dtos import (
    ConsolidationDecisionDto,
    ConsolidationDetailDto,
    ConsolidationPageDto,
    ConsolidationProposalDto,
    ConsolidationScanDto,
)
from noesis.bounded_context.knowledge.application.handlers.commands.accept_consolidation_handler import (
    AcceptConsolidationCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.propose_consolidation_handler import (
    ProposeConsolidationCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.reject_consolidation_handler import (
    RejectConsolidationCommand,
)
from noesis.bounded_context.knowledge.application.handlers.queries.scan_consolidation_candidates_handler import (
    DEFAULT_ANCHORS,
    DEFAULT_HITS,
    MAX_ANCHORS,
    MAX_HITS,
    ScanConsolidationCandidatesQuery,
)
from noesis.bounded_context.knowledge.application.handlers.queries.show_consolidation_handler import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    ListConsolidationsQuery,
    ShowConsolidationQuery,
)
from noesis.bounded_context.knowledge.application.services.inputs import SourceInput
from noesis.bounded_context.knowledge.domain.entities.consolidation import (
    MAX_MEMBERS,
    MIN_MEMBERS,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    ConsolidationId,
    ConsolidationStateEnum,
    DismissalReasonKindEnum,
    Key,
    RecordId,
    Tag,
)
from noesis.core import Environment
from noesis.exceptions import InvalidKeyError, InvalidRecordIdError, InvalidSlugError
from noesis.interfaces.cli import output
from noesis.interfaces.cli.actor import resolve_actor
from noesis.interfaces.cli.bootstrap import ConsolidationHandlers, with_consolidation
from noesis.interfaces.cli.bootstrap.retrieval_handlers_builder import trigger_index_sync
from noesis.interfaces.cli.commands.record_commands import (
    BodyOption,
    SourceIdOption,
    SourceOption,
    parse_sources,
)
from noesis.interfaces.cli.options import JsonOption
from noesis.interfaces.cli.record_inputs import STDIN_MARKER, usage
from noesis.interfaces.cli.responses import (
    ConsolidationDecisionResponse,
    ConsolidationListResponse,
    ConsolidationProposeResponse,
    ConsolidationScanResponse,
    ConsolidationShowResponse,
)
from noesis.interfaces.cli.state import cli_state
from noesis.interfaces.cli.user_presence import require_user_presence

consolidation_app: typer.Typer = typer.Typer(
    help="Find overlapping accepted knowledge and propose one successor for it.",
    no_args_is_help=True,
)

YesOption = Annotated[
    bool, typer.Option("--yes", help="Apply the decision (without it, only preview it).")
]
KeyOption = Annotated[
    str | None,
    typer.Option(
        "--idempotency-key",
        help="Deterministic key of this request (required to apply). The same key resumes an "
        "interrupted run.",
    ),
]


def _record_id(context: typer.Context, value: str, hint: str) -> RecordId:
    try:
        return RecordId(value=value)
    except InvalidRecordIdError:
        raise usage(context, f"{value!r} is not a record id (a 26-character ULID).", hint) from None


def _consolidation_id(context: typer.Context, value: str, hint: str = "ID") -> ConsolidationId:
    try:
        return ConsolidationId(value=value)
    except InvalidRecordIdError:
        raise usage(
            context, f"{value!r} is not a consolidation id (a 26-character ULID).", hint
        ) from None


def _key(context: typer.Context, value: str, hint: str) -> Key:
    try:
        return Key(value=value)
    except InvalidKeyError:
        raise usage(context, f"{value!r} is not a valid project key.", hint) from None


def _text(context: typer.Context, value: str | None, hint: str) -> str:
    if value is None or not value.strip():
        raise usage(context, f"Give a non-empty {hint}.", hint)
    return value


def _require_key(context: typer.Context, applying: bool, key: str | None) -> None:
    if applying and not (key and key.strip()):
        raise usage(context, "--idempotency-key is required to apply.", "--idempotency-key")


@consolidation_app.command("scan")
def scan(
    context: typer.Context,
    record: Annotated[
        str | None, typer.Option("--record", help="Scan around this accepted record.")
    ] = None,
    project: Annotated[
        str | None, typer.Option("--project", help="Scan this project's accepted knowledge.")
    ] = None,
    global_scope: Annotated[
        bool, typer.Option("--global", help="Scan the space-wide accepted knowledge.")
    ] = False,
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, max=MAX_HITS, help="Most similar records per anchor."),
    ] = DEFAULT_HITS,
    anchors: Annotated[
        int,
        typer.Option("--anchors", min=1, max=MAX_ANCHORS, help="Most anchors per page."),
    ] = DEFAULT_ANCHORS,
    cursor: Annotated[
        str | None, typer.Option("--cursor", help="The previous page's next_cursor.")
    ] = None,
    include_dismissed: Annotated[
        bool,
        typer.Option(
            "--include-dismissed", help="Label, instead of hide, pairs judged distinct before."
        ),
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Rank accepted records that may overlap; nothing is written and ranks are not scores."""
    chosen: int = sum((record is not None, project is not None, global_scope))
    if chosen != 1:
        raise usage(context, "Give exactly one of --record, --project or --global.", "--record")
    if cursor is not None and record is not None:
        raise usage(context, "--cursor does not apply to --record.", "--cursor")
    anchor: RecordId | None = _record_id(context, record, "--record") if record else None
    project_key: Key | None = _key(context, project, "--project") if project else None
    env: Environment = cli_state(context).environment()

    async def run(handlers: ConsolidationHandlers) -> ConsolidationScanDto:
        return await handlers.scan.handle(
            ScanConsolidationCandidatesQuery(
                space_key=Key(value=env.knowledge.knowledge_space),
                record_id=anchor,
                project=project_key,
                space_wide=global_scope,
                hits=limit,
                anchors=anchors,
                cursor=cursor,
                include_dismissed=include_dismissed,
            )
        )

    result: ConsolidationScanDto = asyncio.run(with_consolidation(env, run, needs_similarity=True))
    output.emit(ConsolidationScanResponse.from_dto(result))


@consolidation_app.command("propose")
def propose(
    context: typer.Context,
    member: Annotated[
        list[str] | None,
        typer.Option("--member", help=f"An original ({MIN_MEMBERS} to {MAX_MEMBERS}; repeatable)."),
    ] = None,
    title: Annotated[str | None, typer.Option("--title", help="The successor's title.")] = None,
    body: BodyOption = None,
    rationale: Annotated[
        str | None, typer.Option("--rationale", help="Why the originals overlap.")
    ] = None,
    tag: Annotated[
        list[str] | None, typer.Option("--tag", help="A tag of the successor (repeatable).")
    ] = None,
    source: SourceOption = None,
    source_id: SourceIdOption = None,
    reconsider: Annotated[
        str | None,
        typer.Option("--reconsider", help="The distinct dismissal to override, when asked."),
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Validate and show the plan; write nothing.")
    ] = False,
    idempotency_key: KeyOption = None,
    as_json: JsonOption = False,
) -> None:
    """Propose a new successor and one proposed `supersedes` for each original; accepts nothing."""
    ids: list[str] = list(member or [])
    if not MIN_MEMBERS <= len(ids) <= MAX_MEMBERS:
        raise usage(context, f"Give {MIN_MEMBERS} to {MAX_MEMBERS} --member values.", "--member")
    members: tuple[RecordId, ...] = tuple(_record_id(context, item, "--member") for item in ids)
    if len(set(members)) != len(members):
        raise usage(context, "Each --member must be given once.", "--member")
    text: str = _text(context, title, "--title")
    if body is None:
        raise usage(context, "Give the text with --body (use `-` for stdin).", "--body")
    content: str = _text(context, sys.stdin.read() if body == STDIN_MARKER else body, "--body")
    why: str = _text(context, rationale, "--rationale")
    _require_key(context, not dry_run, idempotency_key)
    sources: tuple[SourceInput, ...] = parse_sources(context, source, source_id)
    try:
        tags: tuple[Tag, ...] = tuple(Tag(value=item) for item in tag or ())
    except InvalidSlugError:
        raise usage(
            context, "A tag is lowercase letters, digits and single hyphens.", "--tag"
        ) from None
    earlier: ConsolidationId | None = (
        _consolidation_id(context, reconsider, "--reconsider") if reconsider else None
    )
    env: Environment = cli_state(context).environment()
    actor: Actor = resolve_actor(env.identity)

    async def run(handlers: ConsolidationHandlers) -> ConsolidationProposalDto:
        return await handlers.propose.handle(
            ProposeConsolidationCommand(
                space_key=Key(value=env.knowledge.knowledge_space),
                actor=actor,
                apply=not dry_run,
                idempotency_key=idempotency_key,
                member_ids=members,
                title=text,
                body=content,
                rationale=why,
                tags=tags,
                sources=sources,
                reconsider_id=earlier,
            )
        )

    result: ConsolidationProposalDto = asyncio.run(with_consolidation(env, run))
    if not result.dry_run and not result.replayed:
        trigger_index_sync(env)
    output.emit(ConsolidationProposeResponse.from_dto(result))


@consolidation_app.command("show")
def show(
    context: typer.Context,
    consolidation_id: Annotated[str, typer.Argument(help="Id of the consolidation.")],
    as_json: JsonOption = False,
) -> None:
    """Show a consolidation: its originals, proposals, derived progress and who may decide it."""
    target: ConsolidationId = _consolidation_id(context, consolidation_id)
    env: Environment = cli_state(context).environment()
    actor: Actor = resolve_actor(env.identity)

    async def run(handlers: ConsolidationHandlers) -> ConsolidationDetailDto:
        return await handlers.show.handle(
            ShowConsolidationQuery(
                space_key=Key(value=env.knowledge.knowledge_space),
                actor=actor,
                consolidation_id=target,
            )
        )

    result: ConsolidationDetailDto = asyncio.run(with_consolidation(env, run))
    output.emit(ConsolidationShowResponse.from_dto(result))


@consolidation_app.command("list")
def list_consolidations(
    context: typer.Context,
    project: Annotated[
        str | None, typer.Option("--project", help="This project's consolidations.")
    ] = None,
    global_scope: Annotated[
        bool, typer.Option("--global", help="The space-wide consolidations.")
    ] = False,
    state: Annotated[
        ConsolidationStateEnum | None, typer.Option("--state", help="Only this state.")
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, max=MAX_LIST_LIMIT, help="Page size."),
    ] = DEFAULT_LIST_LIMIT,
    cursor: Annotated[
        str | None, typer.Option("--cursor", help="The previous page's next_cursor.")
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """List consolidations of one project or of the space-wide records, ascending id."""
    if (project is not None) == global_scope:
        raise usage(context, "Give exactly one of --project or --global.", "--project")
    project_key: Key | None = _key(context, project, "--project") if project else None
    env: Environment = cli_state(context).environment()

    async def run(handlers: ConsolidationHandlers) -> ConsolidationPageDto:
        return await handlers.list_consolidations.handle(
            ListConsolidationsQuery(
                space_key=Key(value=env.knowledge.knowledge_space),
                project=project_key,
                space_wide=global_scope,
                state=state,
                limit=limit,
                cursor=cursor,
            )
        )

    result: ConsolidationPageDto = asyncio.run(with_consolidation(env, run))
    output.emit(ConsolidationListResponse.from_dto(result))


@consolidation_app.command("accept")
def accept(
    context: typer.Context,
    consolidation_id: Annotated[str, typer.Argument(help="Id of the consolidation.")],
    reason: Annotated[
        str | None, typer.Option("--reason", help="Why; stored on each decision.")
    ] = None,
    yes: YesOption = False,
    idempotency_key: KeyOption = None,
    as_json: JsonOption = False,
) -> None:
    """Accept the successor, then each `supersedes`; the originals are superseded, never deleted.

    Without --yes nothing is written: the result shows each step and who may take it. A failed
    step exits 1 with every step's outcome; run it again with the same key to resume.
    """
    target: ConsolidationId = _consolidation_id(context, consolidation_id)
    _require_key(context, yes, idempotency_key)
    env: Environment = cli_state(context).environment()
    actor: Actor = resolve_actor(env.identity)
    require_user_presence(actor, applying=yes)

    async def run(handlers: ConsolidationHandlers) -> ConsolidationDecisionDto:
        return await handlers.accept.handle(
            AcceptConsolidationCommand(
                space_key=Key(value=env.knowledge.knowledge_space),
                actor=actor,
                apply=yes,
                idempotency_key=idempotency_key,
                consolidation_id=target,
                reason=reason,
            )
        )

    result: ConsolidationDecisionDto = asyncio.run(with_consolidation(env, run))
    if yes and not result.replayed:
        trigger_index_sync(env)
    output.emit(ConsolidationDecisionResponse.from_dto(result))


@consolidation_app.command("reject")
def reject(
    context: typer.Context,
    consolidation_id: Annotated[str, typer.Argument(help="Id of the consolidation.")],
    reason_kind: Annotated[
        DismissalReasonKindEnum,
        typer.Option(
            "--reason-kind",
            help="distinct: remember the pair as different; poor_draft, other: do not.",
        ),
    ],
    reason: Annotated[str, typer.Option("--reason", help="Why (required; stored).")],
    yes: YesOption = False,
    idempotency_key: KeyOption = None,
    as_json: JsonOption = False,
) -> None:
    """Dismiss a consolidation and retract what it proposed; originals are never touched.

    Without --yes nothing is written. Once acceptance has started a consolidation cannot be
    dismissed any more.
    """
    target: ConsolidationId = _consolidation_id(context, consolidation_id)
    why: str = _text(context, reason, "--reason")
    _require_key(context, yes, idempotency_key)
    env: Environment = cli_state(context).environment()
    actor: Actor = resolve_actor(env.identity)
    require_user_presence(actor, applying=yes)

    async def run(handlers: ConsolidationHandlers) -> ConsolidationDecisionDto:
        return await handlers.reject.handle(
            RejectConsolidationCommand(
                space_key=Key(value=env.knowledge.knowledge_space),
                actor=actor,
                apply=yes,
                idempotency_key=idempotency_key,
                consolidation_id=target,
                reason_kind=reason_kind,
                reason=why,
            )
        )

    result: ConsolidationDecisionDto = asyncio.run(with_consolidation(env, run))
    if yes and not result.replayed:
        trigger_index_sync(env)
    output.emit(ConsolidationDecisionResponse.from_dto(result))
