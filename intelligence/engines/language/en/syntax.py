"""Syntactic structures produced by the English shallow parser."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .tokenizer import Token


@dataclass
class NP:
    tokens: list[Token]
    head: Token | None                   # None for elided heads ("gives 2 to Anna") or nominalised adjectives
    det: Token | None = None
    quant: str | None = None             # all | some | no | any | most | few | many ...
    number: float | None = None          # explicit cardinality ("5 apples")
    adjs: list[Token] = field(default_factory=list)
    modifiers: list[Token] = field(default_factory=list)       # extra nouns forming a compound ("school bus")
    of_np: "NP | None" = None
    possessor: "NP | None" = None
    kind: str = "common"                 # pron | name | common | wh | num | nominal_adj | time
    wh: str | None = None                # who | what | which | how_many | how_much | whose
    definite: bool | None = None
    plural: bool = False
    pron_features: dict[str, Any] = field(default_factory=dict)
    members: list["NP"] = field(default_factory=list)          # coordinated NPs ("Alice and Bob")
    coord: str | None = None             # and | or
    elided_head: bool = False
    measure_unit: str | None = None      # canonical unit when this NP is "30 years", "2 kg"
    span: tuple[int, int] = (0, 0)
    superlative: Token | None = None     # nominal superlative: "the youngest"
    possessive_marker: bool = False

    @property
    def text(self) -> str:
        return " ".join(t.text for t in self.tokens)

    @property
    def head_lemma(self) -> str | None:
        return self.head.lemma if self.head else None


@dataclass
class AdjP:
    """Adjective phrase incl. comparison: 'older than Peter', 'as old as John', 'the youngest'."""

    adj: Token
    base: str
    degree: str                          # pos | cmp | sup
    standard: NP | None = None           # complement of "than"/"as"
    equative: bool = False               # as ADJ as
    periphrastic: str | None = None      # more | less | most | least
    intensifiers: list[Token] = field(default_factory=list)
    measure: NP | None = None            # "30 years old", "1.8 meters tall"
    neg_equative: bool = False
    tokens: list[Token] = field(default_factory=list)
    span: tuple[int, int] = (0, 0)


@dataclass
class PP:
    prep: Token
    np: NP | None
    tokens: list[Token]
    span: tuple[int, int] = (0, 0)
    stranded: bool = False


@dataclass
class VG:
    tokens: list[Token]
    main: Token | None
    auxes: list[Token] = field(default_factory=list)
    neg: bool = False
    tense: str = "present"               # past | present | future
    aspect: str | None = None            # progressive | perfect | perfect_progressive
    voice: str = "active"
    modal: str | None = None
    copula: bool = False
    lemma: str = ""
    adverbs: list[Token] = field(default_factory=list)
    particle: Token | None = None
    span: tuple[int, int] = (0, 0)

    @property
    def finite_form(self) -> str | None:
        return None


@dataclass
class Clause:
    tokens: list[Token]
    connective: str | None = None        # subordinator/coordinator introducing the clause
    connective_role: str | None = None   # cause | condition | contrast | temporal_before | ... | coordinate | complement
    mood: str = "declarative"            # declarative | interrogative | imperative
    subject: NP | None = None
    vg: VG | None = None
    objects: list[NP] = field(default_factory=list)
    complement: Any = None               # NP | AdjP | PP (copular predicate)
    pps: list[PP] = field(default_factory=list)
    advs: list[Token] = field(default_factory=list)
    infinitive: "Clause | None" = None
    time_nps: list[NP] = field(default_factory=list)
    wh: NP | None = None                 # fronted wh-phrase (variable)
    wh_adv: str | None = None            # where | when | why | how | how_adj
    wh_adj: Token | None = None          # "how old"
    question_kind: str | None = None     # yes_no | wh_subject | wh_object | wh_complement | wh_adjunct | wh_degree
    inherited_subject: bool = False
    leftovers: list[Token] = field(default_factory=list)
    span: tuple[int, int] = (0, 0)
    sentence_index: int = 0
    index: int = 0


@dataclass
class ParsedSentence:
    tokens: list[Token]
    text: str
    clauses: list[Clause]
    discourse_markers: list[Token] = field(default_factory=list)   # leading/trailing interjections
    vocative: NP | None = None
    terminal: str | None = None          # . ! ? or None
    coverage: float = 1.0                # share of word tokens consumed by recognised structure
    index: int = 0
    notes: list[str] = field(default_factory=list)
