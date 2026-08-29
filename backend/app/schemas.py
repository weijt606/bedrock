"""
Bedrock — the wire contract.

Everything the front end receives is defined here. If you are building the UI or
the game layer, this file plus docs/API.md is all you need; nothing else in the
backend leaks into the response.

One rule governs every field below: **a language model never states a fact.**
LLMs plan the dig, parse messy rows and classify entities. Every claim that
reaches the user carries a `Source` pointing back at Cala.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
#  input
# --------------------------------------------------------------------------- #


class InputKind(str, Enum):
    text = "text"
    image = "image"
    audio = "audio"


class SampleRequest(BaseModel):
    """POST /v1/samples"""

    kind: InputKind = InputKind.text
    text: str | None = Field(None, max_length=400, description="Product or brand name, when kind=text")
    image_b64: str | None = Field(None, description="Base64 image payload, when kind=image")
    audio_b64: str | None = Field(None, description="Base64 audio payload, when kind=audio")
    mime: str | None = Field(None, description="MIME type for image/audio payloads")
    depth: int = Field(4, ge=1, le=6, description="How many ownership hops to attempt")
    include: list[Literal["ownership", "supply", "statute", "flags", "siblings"]] = Field(
        default_factory=lambda: ["ownership", "supply", "statute", "flags", "siblings"]
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{"kind": "text", "text": "Chupa Chups", "depth": 4}]
        }
    }


# --------------------------------------------------------------------------- #
#  provenance
# --------------------------------------------------------------------------- #


class Source(BaseModel):
    """Where a fact came from. Rendered as the hover citation in the UI."""

    query: str = Field(description="The exact string sent to Cala")
    endpoint: Literal["knowledge/query", "knowledge/search", "entities"] = "knowledge/query"
    latency_s: float = Field(description="Observed round trip; 0.5s means it was already warm")
    cached: bool = False
    documents: list[str] = Field(default_factory=list, description="Source document URLs Cala returned")
    fact_ids: list[str] = Field(default_factory=list, description="Cala explainability fact ids")


# --------------------------------------------------------------------------- #
#  the core sample
# --------------------------------------------------------------------------- #


class EntityKind(str, Enum):
    company = "company"
    person = "person"
    family = "family"
    fund = "fund"
    foundation = "foundation"
    unknown = "unknown"


class Layer(BaseModel):
    """One step up the ownership chain. The UI renders these as the dig."""

    index: int
    name: str
    kind: EntityKind = EntityKind.unknown
    country: str | None = Field(None, description="ISO-3166 alpha-2, when known")
    city: str | None = None
    address: str | None = None
    stake_percent: float | None = None
    relationship: str | None = Field(None, description="e.g. 'direct parent', 'majority owner'")
    detail: list[str] = Field(default_factory=list, description="Supporting lines, already human readable")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Assay agent score")
    terminal: bool = Field(False, description="True when this layer is a human being or family")
    source: Source


class SupplyNode(BaseModel):
    """A manufacturer, co-packer or factory group behind the product."""

    name: str
    role: str | None = None
    country: str | None = None
    detail: str | None = None
    shared_with: list[str] = Field(
        default_factory=list, description="Other brands known to use the same factory group"
    )
    source: Source


class Statute(BaseModel):
    """A law that governs what the product must declare."""

    name: str
    number: str | None = None
    title: str | None = None
    summary: str | None = None
    provisions: list[str] = Field(default_factory=list)
    source: Source


class Flag(BaseModel):
    """A matter of public record — litigation, a sanctions listing, a regulator action.

    Facts only. Bedrock never scores or judges a company; it reports what is filed
    and lets the reader decide. `severity` describes the *type* of record, not our
    opinion of the company.
    """

    kind: Literal["litigation", "sanctions", "regulatory", "recall"]
    title: str
    parties: str | None = None
    summary: str | None = None
    severity: Literal["record", "pending", "decided"] = "record"
    source: Source


class Gap(BaseModel):
    """A question we asked that has no answer anywhere on the public record.

    These are load-bearing, not errors. The most interesting thing Bedrock finds is
    frequently the thing nobody is required to write down.

    A gap is only trustworthy once the same question has been asked several ways.
    Cala answers a *phrasing*, not an intent: `Chupa Chups.raw_material_origin`
    returns 0 rows while "What are Chupa Chups made of and where do the ingredients
    come from?" returns 23. `attempts` records every phrasing that came back empty,
    so the UI can prove the silence rather than assert it.
    """

    query: str
    reason: Literal["no_rows", "too_complex", "error", "rate_limited"] = "no_rows"
    note: str | None = None
    latency_s: float = 0.0
    attempts: list[str] = Field(
        default_factory=list,
        description="Every phrasing tried before declaring this a gap, in order",
    )


# --------------------------------------------------------------------------- #
#  game surface
# --------------------------------------------------------------------------- #


class GuessPrompt(BaseModel):
    """Pre-computed question the game layer can put to the player before revealing
    the chain. `answer` is withheld from the stream until the matching layer lands."""

    id: Literal["ends_in_country", "hops_to_human", "still_domestic"]
    question: str
    options: list[str]
    answer: str | None = Field(None, description="Null while the dig is in flight")


class Score(BaseModel):
    hops_to_human: int = 0
    countries: list[str] = Field(default_factory=list)
    ends_in: str | None = None
    origin_country: str | None = None
    left_home: bool = Field(False, description="True when ownership ends outside the country of origin")
    siblings_count: int = 0
    gaps_count: int = 0


class Subject(BaseModel):
    raw_input: str
    resolved_name: str
    entity_id: str | None = None
    entity_type: str | None = None
    description: str | None = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    identified_by: Literal["text", "vision", "speech"] = "text"


class Meta(BaseModel):
    sample_id: str
    started_at: float
    finished_at: float | None = None
    queries_run: int = 0
    cache_hits: int = 0
    total_latency_s: float = 0.0
    agents: list[str] = Field(default_factory=list)
    models: dict[str, str] = Field(
        default_factory=dict, description="Which model served which role this run"
    )


class CoreSample(BaseModel):
    """The finished artefact. GET /v1/samples/{id} returns exactly this."""

    subject: Subject
    layers: list[Layer] = Field(default_factory=list)
    supply: list[SupplyNode] = Field(default_factory=list)
    statutes: list[Statute] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)
    siblings: list[str] = Field(
        default_factory=list, description="Other brands under the same ultimate owner"
    )
    gaps: list[Gap] = Field(default_factory=list)
    guesses: list[GuessPrompt] = Field(default_factory=list)
    score: Score = Field(default_factory=Score)
    meta: Meta


# --------------------------------------------------------------------------- #
#  streaming
# --------------------------------------------------------------------------- #


class EventType(str, Enum):
    accepted = "accepted"          # job created
    subject = "subject"            # input resolved to a product
    plan = "plan"                  # orchestrator decided what to run
    probe = "probe"                # a Cala call started — drives the "digging" animation
    layer = "layer"                # an ownership layer landed
    supply = "supply"              # a supply node landed
    statute = "statute"            # a regulation landed
    flag = "flag"                  # a public record landed
    gap = "gap"                    # a query came back empty
    siblings = "siblings"          # sibling brands landed
    score = "score"                # running score update
    done = "done"                  # full CoreSample follows
    error = "error"


class StreamEvent(BaseModel):
    """One SSE frame. `event:` is the EventType, `data:` is this object as JSON."""

    type: EventType
    sample_id: str
    seq: int
    at: float
    agent: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
