from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

from .core import normalize_text


FEMALE_X_RE = re.compile(r"女[\u3400-\u9fff]")


@dataclass(frozen=True)
class FemaleXTypeHint:
    entity_type_hint: str
    reasons: tuple[str, ...]


_RITUAL_CUES = (
    "操俎", "持俎", "执俎", "執俎", "操觛", "操觯", "操觶",
    "巫", "祭", "祀", "祠", "祝", "禱", "祷",
)
_PERSON_CUES = (
    "名曰", "其名曰", "有二人", "有人名曰", "有女子名曰", "少女",
    "帝女死焉", "生季", "生寿", "生壽", "之尸", "之屍",
)
_STATE_CUES = ("之国", "之國", "国名", "國名")


def female_x_hit_hash(kind: str, term: str, context: str) -> str:
    """Stable hit identity for entity-split evidence.

    Context identity and hit identity are intentionally different. Two terms
    occurring in the same source window (e.g. 女祭 + 女薎) MUST remain two
    evidence hits, while exact duplicate occurrences of the same term/window
    collapse deterministically.
    """
    payload = f"{kind}|{term}|{normalize_text(context)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def iter_female_x(text: str):
    """Yield conservative 女+one-CJK candidates.

    The generic discovery lane deliberately extracts only the stable two-graph
    shape 女X. Longer strings such as 女娲之肠 or 赤水女子献 belong in the
    exact-seed lane. This keeps toponyms and prose continuations inspectable.
    """
    yield from FEMALE_X_RE.finditer(text)


def classify_female_x_candidate(
    candidate: str,
    left_context: str = "",
    right_context: str = "",
) -> FemaleXTypeHint:
    """Return a cautious type hint, never an identity assertion.

    Classification is intentionally surface/provenance-oriented. The result is
    a routing hint for review queues; it must not be promoted directly to FACT.
    """
    left = left_context[-80:]
    right = right_context[:80]
    local = left + candidate + right
    reasons: list[str] = []

    # Structural place-name tests take precedence. A naive 女X regex otherwise
    # promotes 女床/女烝/女几 into a bogus goddess list.
    if right.startswith("之山") or re.search(rf"曰{re.escape(candidate)}之山", local):
        return FemaleXTypeHint("TOPONYM", ("candidate_followed_by_之山",))
    if right.startswith("之水") or re.search(rf"{re.escape(candidate)}之水", local):
        return FemaleXTypeHint("HYDRONYM", ("candidate_followed_by_之水",))

    # Country/people labels are a separate node class unless a stronger naming
    # construction identifies an individual.
    has_person_naming = any(cue in local for cue in _PERSON_CUES)
    if not has_person_naming and any(cue in right[:12] for cue in _STATE_CUES):
        return FemaleXTypeHint("STATE_OR_PEOPLE", ("near_之国_or_country_cue",))

    ritual_hits = [cue for cue in _RITUAL_CUES if cue in local]
    if ritual_hits and ("有二人" in local or "操" in local or candidate == "女祭"):
        reasons.append("ritual_context:" + ",".join(sorted(set(ritual_hits))))
        return FemaleXTypeHint("RITUAL_PERSON", tuple(reasons))

    person_hits = [cue for cue in _PERSON_CUES if cue in local]
    if person_hits:
        reasons.append("person_or_deity_naming:" + ",".join(sorted(set(person_hits))))
        return FemaleXTypeHint("PERSON_DEITY", tuple(reasons))

    return FemaleXTypeHint("UNKNOWN", ("no_decisive_surface_type_cue",))
