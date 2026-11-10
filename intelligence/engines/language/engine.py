"""Language Understanding Engine (English interface -> ACR).

The engine owns *language-specific* processing and produces a language-neutral ACR document. It
deliberately does not classify intents against a list: speech acts come out of the structure
(mood, interjection analysis, question structure) and the content is semantic structure.
"""

from __future__ import annotations

from ...algorithms.confidence import weighted_geometric
from ...core.contracts import InputPacket, LanguageResult
from ...core.engine import Engine, EngineInfo, EngineStatus, traced
from ...core.errors import EngineError
from ...representation import Intention
from .en.pipeline import EnglishPipeline, vocabulary


class LanguageEngine(Engine):
    info = EngineInfo(
        key="language", name="Language Understanding Engine", status=EngineStatus.IMPLEMENTED,
        summary="English morphology, tagging, shallow parsing and semantic construction into ACR.",
        depends_on=("input",),
        capabilities=(
            "tokenisation incl. contractions, numbers, times, emoji", "sentence segmentation", "inflectional morphology (analysis + generation)",
            "rule-based POS tagging with contextual disambiguation", "NP/VP/PP/clause chunk parsing incl. passives, coordination, subordination",
            "negation scope on predicates", "comparatives/equatives/superlatives mapped to dimensions", "event role assignment (dative alternation, passive)",
            "questions: yes/no, wh-subject/object/adjunct/degree, ellipsis", "pronoun/definite/ordinal reference nodes with agreement features",
            "arithmetic sub-language", "typo and elongation repair", "speech acts from structure"),
        limitations=(
            "Shallow parser: no full recursive grammar, relative clauses are only partly analysed, gapping/ellipsis beyond simple fragments is unsupported.",
            "Lexicon is authored and modest (~200 verbs, ~60 gradable adjectives); unknown words are guessed from morphology and may be mis-tagged.",
            "Quantifier scope, collective vs distributive readings and metaphor are not modelled.",
            "Interpretation confidence is a heuristic evidence score, not a probability."),
    )

    def __init__(self) -> None:
        super().__init__()
        self.pipeline = EnglishPipeline()

    def self_check(self) -> tuple[bool, str]:
        from ...core.contracts import InputPacket
        from datetime import datetime, timezone
        pkt = InputPacket("John is older than Peter.", "John is older than Peter.", "en", 0.9, "probe", datetime.now(timezone.utc))
        res = self._analyze(pkt)
        ok = any(n.KIND == "proposition" and n.predicate == "rel.exceeds" for n in res.doc.nodes.values())  # type: ignore[attr-defined]
        return ok, f"comparative parse probe {'passed' if ok else 'FAILED'}; lexicon size {len(vocabulary())} word forms"

    @traced("analyze")
    def analyze(self, packet: InputPacket) -> LanguageResult:
        try:
            return self._analyze(packet)
        except Exception as exc:  # noqa: BLE001
            raise EngineError("language", "analyze", f"{type(exc).__name__}: {exc}", cause=exc) from exc

    def _analyze(self, packet: InputPacket) -> LanguageResult:
        analysis = self.pipeline.analyze(packet.text, now=packet.received_at)
        doc = analysis.doc
        tokens = [{"text": t.text, "lemma": t.lemma, "pos": t.pos, "sentence": t.sentence,
                   **({"corrected_from": t.corrected_from} if t.corrected_from else {})} for t in analysis.tokens]
        words = [t for t in analysis.tokens if t.pos not in ("PUNCT", "EMOJI")]
        unknown = [t for t in words if t.pos in ("NOUN", "PROPN") and t.lemma.isalpha() and t.lemma.lower() not in vocabulary()
                   and t.pos != "PROPN" and not t.text[:1].isupper()]
        lexical = 1.0 - (len(unknown) / len(words) if words else 0.0)
        repair = max(0.4, 1.0 - 0.1 * len(analysis.corrections))
        unresolved_struct = 0
        for p in analysis.sentences:
            for c in p.clauses:
                if c.leftovers:
                    unresolved_struct += len(c.leftovers)
        total_words = max(1, len(words))
        structure = max(0.2, 1.0 - unresolved_struct / total_words)
        comps = {"coverage": max(0.05, analysis.coverage), "lexical": max(0.05, lexical), "structure": structure, "repair": repair}
        conf = weighted_geometric(comps, {"coverage": 3.0, "lexical": 1.0, "structure": 2.0, "repair": 1.0})
        if analysis.math is not None:
            conf = 0.98 if "error" not in analysis.math else 0.7
        acts = [n.act for n in doc.of_kind(Intention)]
        unsupported = []
        if not doc.roots:
            unsupported.append("no communicative act could be derived from the input")
        if unknown:
            unsupported.append("words not in lexicon: " + ", ".join(sorted({t.text for t in unknown})[:8]))
        return LanguageResult(packet=packet, doc=doc, tokens=tokens, corrections=analysis.corrections, coverage=analysis.coverage,
                              interpretation_confidence=conf, confidence_components=comps, notes=analysis.notes, speech_acts=acts,
                              sentences=len(analysis.sentences), math=analysis.math, unsupported=unsupported)
