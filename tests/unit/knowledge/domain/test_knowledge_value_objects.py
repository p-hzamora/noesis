"""Value objects of the Knowledge domain (spec 20-domain)."""

import hashlib

import pytest
from pydantic import ValidationError

from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    ActorKindEnum,
    Applicability,
    ContentHash,
    Key,
    RecordId,
    Slug,
    SpaceId,
    Tag,
)
from noesis.exceptions import (
    InvalidContentHashError,
    InvalidKeyError,
    InvalidRecordError,
    InvalidRecordIdError,
    InvalidSlugError,
)

pytestmark = pytest.mark.unit

VALID_ULID: str = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


@pytest.mark.parametrize("value", [VALID_ULID, "7ZZZZZZZZZZZZZZZZZZZZZZZZZ", "0" * 26])
def test_record_id_accepts_valid_and_existing_ulids(value: str) -> None:
    assert RecordId(value=value).value == value
    assert SpaceId(value=value).value == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        VALID_ULID.lower(),
        VALID_ULID[:-1],
        VALID_ULID + "A",
        "8" + VALID_ULID[1:],  # first char above 7 overflows 128 bits
        "I" + VALID_ULID[1:],  # I, L, O, U are not Crockford base32
        "01ARZ3NDEKTSV4RRFFQ69G5FAU",
    ],
)
def test_record_id_rejects_invalid_ulids_with_knowledge_001(value: str) -> None:
    with pytest.raises(InvalidRecordIdError) as error:
        RecordId(value=value)
    assert error.value.error_code == "KNOWLEDGE_001_INVALID_RECORD_ID"
    with pytest.raises(InvalidRecordIdError):
        SpaceId(value=value)


def test_content_hash_of_bytes_is_sha256_prefixed_hex() -> None:
    digest: ContentHash = ContentHash.of(b"hello")

    assert digest.value == "sha256:" + hashlib.sha256(b"hello").hexdigest()
    assert ContentHash(value=digest.value) == digest


@pytest.mark.parametrize(
    "value",
    [
        "",
        "abc",
        "sha256:",
        "sha256:" + "a" * 63,
        "sha256:" + "a" * 65,
        "sha256:" + "A" * 64,
        "md5:" + "a" * 64,
        "sha256:" + "g" * 64,
    ],
)
def test_content_hash_rejects_malformed_values_with_knowledge_003(value: str) -> None:
    with pytest.raises(InvalidContentHashError) as error:
        ContentHash(value=value)
    assert error.value.error_code == "KNOWLEDGE_003_INVALID_CONTENT_HASH"


@pytest.mark.parametrize(
    ("raw", "normalised", "facet"),
    [
        ("billing", "billing", None),
        ("  Billing  ", "billing", None),
        ("Area:Billing", "area:billing", "area"),
        ("a-b:c-d-1", "a-b:c-d-1", "a-b"),
    ],
)
def test_tag_normalises_and_exposes_facet(raw: str, normalised: str, facet: str | None) -> None:
    tag: Tag = Tag(value=raw)

    assert tag.value == normalised
    assert tag.facet == facet


@pytest.mark.parametrize(
    "raw", ["", "  ", "two words", "a:", ":b", "a:b:c", "-a", "a-", "a--b", "a_b", "x" * 65]
)
def test_tag_rejects_invalid_slug_parts_with_knowledge_002(raw: str) -> None:
    with pytest.raises(InvalidSlugError) as error:
        Tag(value=raw)
    assert error.value.error_code == "KNOWLEDGE_002_INVALID_SLUG"


@pytest.mark.parametrize("value", ["decision", "gotcha-2", "a" * 64])
def test_slug_accepts_lowercase_words_joined_by_hyphens(value: str) -> None:
    assert Slug(value=value).value == value


@pytest.mark.parametrize("value", ["", "Decision", "a b", "a--b", "-a", "a-", "a" * 65, "a_b"])
def test_slug_rejects_invalid_values_with_knowledge_002(value: str) -> None:
    with pytest.raises(InvalidSlugError, match="Invalid slug"):
        Slug(value=value)


@pytest.mark.parametrize("value", ["noesis", "My.Repo_1-x", "0abc", "a" * 128])
def test_key_accepts_names_and_keeps_them_as_written(value: str) -> None:
    assert Key(value=value).value == value


@pytest.mark.parametrize("value", ["", " ", "a b", ".hidden", "-x", "_x", "a/b", "a" * 129])
def test_key_rejects_invalid_values_with_knowledge_004(value: str) -> None:
    with pytest.raises(InvalidKeyError) as error:
        Key(value=value)
    assert error.value.error_code == "KNOWLEDGE_004_INVALID_KEY"


def test_actor_trims_name_and_rejects_blank_with_knowledge_007() -> None:
    actor: Actor = Actor(kind=ActorKindEnum.USER, name="  pablo ")

    assert actor.name == "pablo"
    assert actor.session is None
    with pytest.raises(InvalidRecordError):
        Actor(kind=ActorKindEnum.AGENT, name="   ")


def test_actor_rejects_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        Actor(kind="robot", name="x")  # type: ignore[arg-type]


def test_applicability_without_project_is_space_wide() -> None:
    applicability: Applicability = Applicability()

    assert applicability.project_id is None
    assert applicability.tags == frozenset()
    assert applicability.sorted_tags == ()


def test_applicability_sorts_tags_stably() -> None:
    tags: frozenset[Tag] = frozenset({Tag(value="b"), Tag(value="area:x"), Tag(value="a")})

    result: Applicability = Applicability(project_id=RecordId(value=VALID_ULID), tags=tags)

    assert [t.value for t in result.sorted_tags] == ["a", "area:x", "b"]


def test_value_objects_are_immutable() -> None:
    key: Key = Key(value="noesis")
    with pytest.raises(ValidationError):
        key.value = "other"  # type: ignore[misc]
