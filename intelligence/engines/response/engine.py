"""Response Generation Engine: compositional, style-adaptive, repetition-aware English realisation of a ContentPlan.

Design rules
  * The plan (structured, language-neutral) fixes *what is said*. Variation only chooses *how it is framed*: every variant of a
    message states the same entities, relation, polarity and values (checked by tests across many seeds).
  * There are no lists of whole canned replies. Sentences are composed from slots (opener, name, core clause, support clause,
    hedge, follow-up, emoji). Alternatives are *skeleton options* with metadata (formality centre, minimum warmth, tags).
  * Choices are weighted by the style profile (formality distance, warmth, expressiveness, conciseness), penalised when the
    skeleton was used recently in this conversation, and sampled with a seeded RNG (reproducible for tests, varied in use).
  * Repetition awareness: recent skeletons, recent emoji and recent texts are kept in a serialisable state; an identical plan
    asked again gets an acknowledging, shorter rendering instead of the same paragraph.
"""

from __future__ import annotations

import math
import random
import zlib
from dataclasses import dataclass, field
from typing import Any, Callable

from ...core.contracts import ContentPlan, EmotionSignal, ResponseResult
from ...core.engine import Engine, EngineInfo, EngineStatus, traced
from ..language.en.morphology import superlative_form
from . import emoji as emoji_mod
from .realizer import adjective_for, be, cap, dim_noun, join_list, realize_fact, realize_query_prop, summary_to_fact

RECENT_SKELETONS = 14
RECENT_TEXTS = 5


@dataclass
class Opt:
    id: str
    text: str | Callable[["Ctx"], str]
    formality: float | None = None
    min_warmth: float = 0.0
    max_warmth: float = 1.0
    min_expr: float = 0.0
    concise: bool | None = None            # True: only when concise style; False: only when not concise
    tags: tuple[str, ...] = ()
    weight: float = 1.0


@dataclass
class Ctx:
    style: dict
    emotion: EmotionSignal | None
    state: dict
    rng: random.Random
    name: str | None = None
    occasion: dict = field(default_factory=dict)
    used: list[str] = field(default_factory=list)
    contract: bool = True
    verbose: bool = False
    concise: bool = False
    show_steps: bool = False
    repeat: int = 0
    tags: set[str] = field(default_factory=set)


def new_state() -> dict:
    return {"turn": 0, "skeletons": [], "emoji": [], "texts": [], "signatures": [], "greeted": False}


def _decap(s: str) -> str:
    return s[:1].lower() + s[1:] if s.split(" ", 1)[0] in ("The", "It's", "It", "That", "This", "Your", "No", "All", "So") else s


class ResponseGenerationEngine(Engine):
    info = EngineInfo(
        key="response", name="Response Generation Engine", status=EngineStatus.PARTIAL,
        summary="Compositional English realisation with style adaptation, greeting grammar, emoji intelligence and repetition awareness.",
        depends_on=("personality", "emotion", "reasoning"),
        capabilities=("answers for entities/values/numbers/booleans/lists with faithful restatement of the asked proposition",
                      "support (premise) clauses and step explanations driven by style", "honest unknown / underdetermined / contradiction / unsupported renderings",
                      "greetings, farewells, thanks and social replies composed from slots", "emoji decisions with explicit reasons",
                      "repetition tracking across skeletons, emoji and whole texts", "verified-learning acknowledgements (never claims unverified learning)"),
        limitations=("English only. Alternatives are authored skeleton options; the variety is combinatorial but finite and not learned.",
                     "No paraphrase generation beyond the authored skeletons; unusual relations fall back to a generic rendering.",
                     "Style adaptation is limited to the five profile dimensions plus emoji.",
                     "Long multi-paragraph discourse planning is not implemented."),
    )

    # ------------------------------------------------------------------------------------------------------------------------
    def self_check(self) -> tuple[bool, str]:
        text = realize_fact({"predicate": "rel.exceeds", "args": {"greater": "John", "lesser": "Peter", "dimension": "dim.age"}})
        ok = text == "John is older than Peter"
        return ok, "realiser probe" if ok else f"realiser probe produced {text!r}"

    def new_state(self) -> dict:
        return new_state()

    @traced("generate")
    def generate(self, plan: ContentPlan, style: Any, emotion: EmotionSignal | None, state: dict | None, *, seed: int | None = None,
                 name: str | None = None, occasion: dict | None = None) -> ResponseResult:
        st = state if state is not None else new_state()
        style = style.to_dict() if hasattr(style, "to_dict") else dict(style)
        sig = self._signature(plan)
        repeat = sum(1 for s in st["signatures"][-3:] if s == sig)
        base_seed = (seed if seed is not None else random.SystemRandom().randrange(2 ** 31)) ^ zlib.crc32(sig.encode())
        text, ctx = "", None
        for attempt in range(6):
            rng = random.Random(base_seed + attempt * 7919)
            ctx = Ctx(style=style, emotion=emotion, state=st, rng=rng, name=name, occasion=occasion or {}, repeat=repeat,
                      contract=style.get("formality", 0.45) < 0.62, concise=style.get("conciseness", 0.5) > 0.7,
                      verbose=style.get("conciseness", 0.5) < 0.35, show_steps=bool(style.get("show_steps")))
            text = self._compose(plan, ctx)
            if text not in st["texts"][-RECENT_TEXTS:] or repeat > 0:
                break
        emoji_list, why = self._emoji(plan, ctx, style)
        if emoji_list:
            text = self._place_emoji(text, emoji_list)
        st["turn"] += 1
        st["skeletons"] = (st["skeletons"] + ctx.used)[-RECENT_SKELETONS:]
        st["texts"] = (st["texts"] + [text])[-RECENT_TEXTS:]
        st["signatures"] = (st["signatures"] + [sig])[-6:]
        st["emoji"] = (emoji_list + st["emoji"])[:6]
        if any(m["type"] == "greet" for m in plan.messages):
            st["greeted"] = True
        variation = {"skeletons": ctx.used, "emoji": emoji_list, "emoji_reason": why, "repeat": repeat, "seed": base_seed, "attempts": attempt + 1,
                     "style": {k: style.get(k) for k in ("formality", "warmth", "conciseness", "expressiveness", "emoji_level")}}
        return ResponseResult(text=text, plan=plan, variation=variation, emoji=emoji_list)

    @staticmethod
    def _signature(plan: ContentPlan) -> str:
        parts = []
        for m in plan.messages:
            core = {k: m.get(k) for k in ("type", "value", "entity", "entities", "owner", "attribute", "query", "alternatives", "facts", "status", "code", "title")}
            parts.append(repr(sorted((k, repr(v)) for k, v in core.items() if v is not None)))
        return "|".join(parts)

    # ---- option selection -------------------------------------------------------------------------------------------------
    def pick(self, ctx: Ctx, options: list[Opt], *, fmt: dict | None = None) -> str:
        warmth, expr, form = ctx.style.get("warmth", 0.6), ctx.style.get("expressiveness", 0.4), ctx.style.get("formality", 0.45)
        eligible, weights = [], []
        for o in options:
            if not (o.min_warmth <= warmth <= o.max_warmth) or expr < o.min_expr:
                continue
            if o.concise is True and not ctx.concise or o.concise is False and ctx.concise:
                continue
            if o.tags and not set(o.tags) <= ctx.tags:
                continue
            w = o.weight
            if o.formality is not None:
                w *= math.exp(-((form - o.formality) ** 2) / 0.07)
            recent = ctx.state["skeletons"][-RECENT_SKELETONS:] + ctx.used
            if o.id in recent:
                w *= 0.04 if recent[::-1].index(o.id) < 6 else 0.25
            eligible.append(o)
            weights.append(max(w, 1e-6))
        if not eligible:
            eligible, weights = options[:1], [1.0]
        o = ctx.rng.choices(eligible, weights=weights, k=1)[0]
        ctx.used.append(o.id)
        t = o.text(ctx) if callable(o.text) else o.text
        return t.format(**fmt) if fmt else t

    # ---- composition ------------------------------------------------------------------------------------------------------------
    def _compose(self, plan: ContentPlan, ctx: Ctx) -> str:
        if ctx.emotion is not None and ctx.emotion.label == "negative" and ctx.emotion.certainty > 0.4:
            ctx.tags.add("upset")
        parts: list[str] = []
        if ctx.repeat and any(m["type"].endswith("_answer") for m in plan.messages):
            parts.append(self.pick(ctx, [Opt("rep.same", "Same answer as before:", 0.4), Opt("rep.again", "Again:", 0.3), Opt("rep.said", "As I said,", 0.5),
                                         Opt("rep.still", "Still the same —", 0.3)]))
        for m in plan.messages:
            fn = getattr(self, f"_m_{m['type']}", None)
            parts.append(fn(m, ctx) if fn else self._m_generic(m, ctx))
        text = " ".join(p.strip() for p in parts if p and p.strip())
        for step in plan.explanation[: (6 if ctx.show_steps else 0)]:
            text += f"\n  • {step}"
        return text

    def _certainty_prefix(self, conf: float | None, ctx: Ctx) -> str:
        if conf is None or conf >= 0.75:
            return ""
        if conf >= 0.5:
            return self.pick(ctx, [Opt("hedge.think", "I think", 0.35), Opt("hedge.seems", "It seems", 0.5), Opt("hedge.probably", "Probably", 0.3)]) + " "
        return self.pick(ctx, [Opt("hedge.notsure", "I'm not very sure, but", 0.3), Opt("hedge.tentative", "Tentatively,", 0.6)]) + " "

    def _support(self, msg: dict, ctx: Ctx) -> str | None:
        sup = msg.get("support") or []
        if not sup or ctx.concise and not ctx.show_steps or ctx.repeat:
            return None
        qp = (msg.get("query") or {}).get("predicate")
        if len(sup) == 1 and qp and sup[0].get("predicate") == qp:
            return None                       # a single direct fact on the same predicate: restating it would add nothing
        seen, clauses = set(), []
        for d in sup:
            c = realize_fact(d, contract=ctx.contract)
            if c not in seen:
                seen.add(c)
                clauses.append(c)
        if not clauses:
            return None
        return join_list(clauses[:5])

    def _with_support(self, core: str, msg: dict, ctx: Ctx, *, allow_front: bool = True) -> str:
        sup = self._support(msg, ctx)
        if not sup:
            return core
        if not ctx.verbose and not ctx.show_steps and ctx.rng.random() < 0.45:
            return core                                     # supporting clauses are optional in the middle ground
        if allow_front and core[:1].isupper() and core.split(" ", 1)[0] not in ("I", "Yes", "No", "So"):
            front = self.pick(ctx, [Opt("sup.since", "Since {s}, {c}", 0.5), Opt("sup.given", "Given that {s}, {c}", 0.7)])
            if front.startswith("Since") or front.startswith("Given"):
                tail = core
                if tail.split(" ", 1)[0] not in ("The", "That", "It's", "It"):
                    return f"{front.format(s=sup, c=tail[:-1] if tail.endswith('.') else tail)}."
                return f"{front.format(s=sup, c=_decap(tail)[:-1] if tail.endswith('.') else _decap(tail))}."
        tail = self.pick(ctx, [Opt("sup.because", "That follows from this: {s}.", 0.5), Opt("sup.reason", "The reasoning: {s}.", 0.6), Opt("sup.basis", "That's based on what I know — {s}.", 0.35)])
        return f"{core} {tail.format(s=sup)}"

    # ---- message realisers ----------------------------------------------------------------------------------------------------------
    def _m_generic(self, m: dict, ctx: Ctx) -> str:
        return m.get("text") or ""

    def _m_entity_answer(self, m: dict, ctx: Ctx) -> str:
        e, rel = m["entity"], m.get("relation", {})
        adj = adjective_for(rel.get("dimension", ""), rel.get("pole", "high"))
        pre = self._certainty_prefix(m.get("confidence"), ctx)
        if adj is None:
            return f"{pre}{e}."
        sup = superlative_form(adj)
        dom = m.get("domain") or []
        of = f" among {join_list(dom)}" if len(dom) >= 2 and not ctx.concise and ctx.rng.random() < 0.4 else ""
        opts = [
            Opt("ent.is_the", f"{e} {be(e)} the {sup}{of}.", 0.5), Opt("ent.the_is", f"The {sup}{of} is {e}.", 0.6),
            Opt("ent.would_be", f"That would be {e} — the {sup}{of}.", 0.3, concise=False), Opt("ent.its", f"It's {e}.", 0.2, concise=True), Opt("ent.bare", f"{e}.", 0.2, concise=True),
            Opt("ent.so", f"So the {sup} is {e}.", 0.3, concise=False), Opt("ent.answer", f"The answer is {e} — the {sup}.", 0.45, concise=False),
        ]
        core = self.pick(ctx, opts)
        if pre:
            core = pre + (_decap(core) if core.split(" ", 1)[0] in ("The", "It's", "That", "So") else core)
        return self._with_support(core, m, ctx, allow_front="ent.bare" not in ctx.used and "ent.its" not in ctx.used)

    def _m_entities_answer(self, m: dict, ctx: Ctx) -> str:
        ents = m["entities"]
        rel = m.get("relation", {})
        adj = adjective_for(rel.get("dimension", ""), "high")
        ref, direction = rel.get("reference"), rel.get("direction", "greater")
        names = join_list(ents)
        if adj is None or not ref:
            return f"{names}."
        from ..language.en.morphology import comparative_form
        comp = comparative_form(adj)
        if direction == "lesser":
            adj_low = adjective_for(rel.get("dimension", ""), "low")
            comp = comparative_form(adj_low) if adj_low else f"less {adj}"
        verb = "are" if len(ents) > 1 else "is"
        core = self.pick(ctx, [Opt("ents.is", f"{names} {verb} {comp} than {ref}.", 0.5), Opt("ents.known", f"As far as I know, {names} {verb} {comp} than {ref}.", 0.5, concise=False),
                               Opt("ents.from", f"From what I've got, that's {names}.", 0.2, concise=False)])
        if m.get("unrelated"):
            core += f" I can't place {join_list(m['unrelated'])} relative to {ref}."
        return self._with_support(core, m, ctx, allow_front=False)

    def _m_boolean_answer(self, m: dict, ctx: Ctx) -> str:
        q = m.get("query", {})
        v = m.get("value")
        pre = self._certainty_prefix(m.get("confidence"), ctx)
        if v is True:
            prop = realize_query_prop(q, contract=ctx.contract)
            if prop is None:
                return pre + self.pick(ctx, [Opt("yes.bare1", "Yes.", 0.4), Opt("yes.bare2", "That's right.", 0.4)])
            P = cap(prop)
            core = self.pick(ctx, [Opt("yes.dash", f"Yes — {prop}.", 0.5), Opt("yes.comma", f"Yes, {prop}.", 0.35), Opt("yes.right", f"That's right: {prop}.", 0.3),
                                   Opt("yes.correct", f"Correct — {prop}.", 0.65, concise=False), Opt("yes.tail", f"{P}, yes.", 0.2), Opt("yes.only", "Yes.", 0.4, concise=True)])
            if pre:
                core = f"{pre.strip()} yes — {prop}." if pre else core
            return self._with_support(core, m, ctx, allow_front=False)
        if v is False:
            actual = m.get("actual_fact")
            if actual:
                act = realize_fact(actual, contract=ctx.contract)
            elif m.get("actual_text"):
                act = m["actual_text"]
            else:
                act = None
            neg = realize_query_prop(q, contract=ctx.contract, force_neg=(q.get("polarity") != "negative"))
            body = act or neg
            if body is None:
                return pre + "No."
            core = self.pick(ctx, [Opt("no.dash", f"No — {body}.", 0.5), Opt("no.comma", f"No, {body}.", 0.35), Opt("no.quite", f"Not quite: {body}.", 0.35),
                                   Opt("no.case", f"That's not the case — {body}.", 0.6, concise=False), Opt("no.only", "No.", 0.3, concise=True)])
            return self._with_support(core, m, ctx, allow_front=False)
        prop = realize_query_prop(q, contract=ctx.contract)
        missing = m.get("missing") or []
        need = f" I'd need {join_list(missing)}." if missing and not ctx.concise else ""
        what = f"whether {prop}" if prop else "that"
        return self.pick(ctx, [Opt("bq.cant", f"I can't say {what}.{need}", 0.5), Opt("bq.dont", f"I don't know {what}.{need}", 0.3),
                               Opt("bq.notsure", f"I don't have enough to tell {what}.{need}", 0.6, concise=False)])

    def _m_value_answer(self, m: dict, ctx: Ctx) -> str:
        d = {"predicate": m["attribute"], "args": {"owner": m["owner"], "value": m["value"]}, "polarity": "positive"}
        clause = realize_fact(d, contract=ctx.contract)
        attr = m["attribute"][5:].replace("_", " ")
        pre = self._certainty_prefix(m.get("confidence"), ctx)
        src = m.get("source")
        opts = [Opt("val.clause", f"{cap(clause)}.", 0.5), Opt("val.its", f"It's {m['value']}.", 0.25, concise=True),
                Opt("val.inv", f"{m['value']} is {'your' if m['owner'] == 'you' else 'the'} {attr}{'' if m['owner'] == 'you' else ' of ' + m['owner']}.", 0.45, concise=False)]
        if src == "user_statement":
            opts.append(Opt("val.told", f"You told me {clause}.", 0.4, min_warmth=0.3, concise=False))
        if src == "seed_curated":
            opts.append(Opt("val.asfar", f"As far as I know, {clause}.", 0.5, concise=False))
        core = self.pick(ctx, opts)
        if pre:
            core = pre + _decap(core)
        if m.get("alternatives") and not ctx.concise:
            core += f" (I also have: {join_list([a['label'] for a in m['alternatives']])}.)"
        if m.get("disputed_note"):
            core += f" {m['disputed_note']}"
        return core

    def _m_number_answer(self, m: dict, ctx: Ctx) -> str:
        v, ex = m["value"], m.get("expression")
        opts = [Opt("num.bare", f"{v}.", 0.3, concise=True), Opt("num.answer", f"The answer is {v}.", 0.5), Opt("num.comes", f"That comes to {v}.", 0.35),
                Opt("num.is", f"{ex} is {v}.", 0.5) if ex else Opt("num.is2", f"It's {v}.", 0.3), Opt("num.eq", f"{ex} = {v}.", 0.3, concise=False) if ex else Opt("num.eq2", f"= {v}.", 0.2, concise=True)]
        return self.pick(ctx, opts)

    def _m_likely_answer(self, m: dict, ctx: Ctx) -> str:
        g = m["generalisation"]
        pat = g.get("pattern")
        tmpl = {"all": "All {n} examples I know have it", "none": "None of the {n} examples I know have it"}.get(pat, "Mixed evidence")
        txt = tmpl.format(n=g.get("positive", 0) + g.get("negative", 0)) + " — so it's probably true in general, but that's a generalisation, not a proof."
        return txt if pat != "none" else txt.replace("probably true", "probably not true")

    def _m_unknown(self, m: dict, ctx: Ctx) -> str:
        what = m.get("what") or "that"
        sugg = m.get("suggestions") or []
        miss = m.get("missing") or []
        core = self.pick(ctx, [Opt("unk.dont", f"I don't know {what}.", 0.4), Opt("unk.have", f"I don't have {what} on record.", 0.5, concise=False),
                               Opt("unk.cant", f"I can't answer that — I don't know {what}.", 0.3), Opt("unk.notknow", "I don't know.", 0.3, concise=True)])
        if sugg:
            labels = [s if isinstance(s, str) else s["label"] for s in sugg]
            core += f" Did you mean {join_list(labels, 'or')}?"
        elif miss and not ctx.concise:
            core += " " + self.pick(ctx, [Opt("unk.need", f"I'd need {join_list(miss)}.", 0.5), Opt("unk.tell", f"If you tell me {join_list(miss)}, I can work with it.", 0.3, min_warmth=0.4)])
        return core

    def _m_underdetermined(self, m: dict, ctx: Ctx) -> str:
        alts = [a["label"] if isinstance(a, dict) else a for a in m["alternatives"]]
        rel = m.get("relation", {})
        adj = adjective_for(rel.get("dimension", ""), rel.get("pole", "high"))
        sup = superlative_form(adj) if adj else "one"
        miss = m.get("missing") or []
        core = self.pick(ctx, [Opt("und.cant", f"I can't tell yet — {join_list(alts, 'or')} could each be the {sup}.", 0.5),
                               Opt("und.open", f"That's still open: it could be {join_list(alts, 'or')}.", 0.3), Opt("und.notenough", f"There isn't enough to decide who is the {sup} — {join_list(alts, 'or')} all fit.", 0.55, concise=False)])
        if miss:
            core += " " + self.pick(ctx, [Opt("und.if", f"If you tell me {join_list(miss)}, I can answer.", 0.4), Opt("und.need", f"I'd need {join_list(miss)}.", 0.5)])
        return core

    def _m_contradiction(self, m: dict, ctx: Ctx) -> str:
        parts = []
        for c in m.get("contradictions", []):
            if c.get("kind") == "ordering_cycle":
                cyc = list(c["cycle"])
                if len(cyc) > 2 and cyc[0] == cyc[-1]:
                    cyc = cyc[:-1]
                clauses = [realize_fact({"predicate": "rel.exceeds", "args": {"greater": a, "lesser": b, "dimension": c.get("dimension", "")}}, contract=ctx.contract)
                           for a, b in zip(cyc, cyc[1:] + cyc[:1])]
                parts.append(f"{join_list(clauses)} can't all be true")
            elif c.get("kind") in ("negation", "different_value"):
                parts.append(f"that conflicts with what I have: {c.get('with')}")
            else:
                parts.append(c.get("note") or "those statements conflict")
        body = "; ".join(parts) or "those statements conflict"
        head = self.pick(ctx, [Opt("con.add", "That doesn't add up:", 0.5), Opt("con.cant", "Something is inconsistent here:", 0.6), Opt("con.hold", "Hold on —", 0.2, min_warmth=0.3)])
        tail = " Which one should I trust?" if not ctx.concise else ""
        return f"{head} {body}.{tail}"

    def _m_undefined_math(self, m: dict, ctx: Ctx) -> str:
        return self.pick(ctx, [Opt("und.math", f"That's undefined: {m.get('error', 'no defined value')}.", 0.5), Opt("und.math2", f"There's no defined answer — {m.get('error', 'undefined')}.", 0.4)])

    def _m_unsupported(self, m: dict, ctx: Ctx) -> str:
        caps = m.get("capabilities") or []
        core = self.pick(ctx, [Opt("uns.cant", "I can't work that out in this version.", 0.5), Opt("uns.beyond", "That's beyond what I can reason about right now.", 0.45), Opt("uns.notyet", "I don't have a way to handle that yet.", 0.3)])
        if caps and not ctx.concise:
            core += f" I can {join_list(caps)}."
        return core

    def _m_stored(self, m: dict, ctx: Ctx) -> str:
        facts = join_list([realize_fact(f, contract=ctx.contract) for f in m["facts"]], "and")
        st = m.get("status", "stored")
        if st == "duplicate":
            return self.pick(ctx, [Opt("sto.dup", f"I already had that: {facts}.", 0.5), Opt("sto.known", f"Yes, I have that already — {facts}.", 0.4)])
        if st == "superseded":
            return self.pick(ctx, [Opt("sto.upd", f"Updated — {facts}, replacing what I had before.", 0.5), Opt("sto.chg", f"Okay, I've changed that: {facts}.", 0.35)])
        return self.pick(ctx, [Opt("sto.got", f"Got it — {facts}.", 0.3), Opt("sto.noted", f"Noted: {facts}.", 0.5), Opt("sto.rem", f"Okay, I'll remember that {facts}.", 0.4, concise=False),
                               Opt("sto.thanks", f"Thanks — {facts}, noted.", 0.35, min_warmth=0.4), Opt("sto.ok", "Noted.", 0.4, concise=True)])

    def _m_not_stored(self, m: dict, ctx: Ctx) -> str:
        return self.pick(ctx, [Opt("ns.cant", f"I couldn't keep that as a fact: {m['reason']}.", 0.5), Opt("ns.kept", f"I've left my information unchanged — {m['reason']}.", 0.45)])

    def _m_learned(self, m: dict, ctx: Ctx) -> str:
        ch = m.get("change") or {}
        key, val = ch.get("key"), ch.get("value")
        if m.get("status") == "proposed":
            return "That would change what everyone in this project sees, so it needs an administrator's approval. I've queued it as a proposal."
        if m.get("status") == "reverted":
            return "Done — I've undone that change."
        if not m.get("verified"):
            return f"I wasn't able to save that: {m.get('reason') or 'it could not be verified'}."
        if m.get("kind") == "fact_correction":
            return self.pick(ctx, [Opt("lrn.fact", "Thanks for the correction — I've saved it for you.", 0.5), Opt("lrn.fact2", "Understood, I've updated what I know for your account.", 0.6)])
        table: dict[tuple, list[Opt]] = {
            ("style.emoji", "none"): [Opt("lrn.noemoji", "Okay — no more emoji.", 0.3), Opt("lrn.noemoji2", "Understood, I'll leave emoji out from now on.", 0.6)],
            ("style.emoji", "more"): [Opt("lrn.moreemoji", "Sure, I'll use a few more emoji.", 0.3)],
            ("style.formality", "formal"): [Opt("lrn.formal", "I'll keep a more formal tone from now on.", 0.6), Opt("lrn.formal2", "Understood — formal it is.", 0.5)],
            ("style.formality", "casual"): [Opt("lrn.casual", "Sounds good, I'll keep it more relaxed.", 0.2), Opt("lrn.casual2", "Okay, casual from here on.", 0.3)],
            ("style.length", "short"): [Opt("lrn.short", "I'll keep my answers shorter.", 0.4), Opt("lrn.short2", "Got it — brief answers.", 0.3)],
            ("style.length", "long"): [Opt("lrn.long", "I'll go into more detail from now on.", 0.5)],
            ("style.warmth", "warm"): [Opt("lrn.warm", "I'll aim to be warmer.", 0.4)], ("style.warmth", "neutral"): [Opt("lrn.neutral", "I'll keep the tone more neutral.", 0.5)],
            ("behavior.show_steps", True): [Opt("lrn.steps", "I'll show my steps from now on.", 0.4), Opt("lrn.steps2", "Okay — I'll include the reasoning.", 0.4)],
            ("behavior.show_steps", False): [Opt("lrn.nosteps", "Okay, I'll just give the answer.", 0.3)],
            ("behavior.ask_clarification", True): [Opt("lrn.ask", "I'll ask when something is unclear.", 0.4)],
            ("behavior.ask_clarification", False): [Opt("lrn.noask", "I'll stop asking and make my best reading instead.", 0.4)],
        }
        if key == "user.preferred_name":
            return self.pick(ctx, [Opt("lrn.name", f"Nice to meet you, {val} — I'll call you {val}.", 0.4), Opt("lrn.name2", f"Okay, {val} it is.", 0.2)])
        opts = table.get((key, val))
        return self.pick(ctx, opts) if opts else "Saved."

    def _m_clarify(self, m: dict, ctx: Ctx) -> str:
        opts = m.get("options", [])
        sur = m.get("surface")
        lead = f"“{sur}”" if sur else "that"
        return self.pick(ctx, [Opt("clr.mean", f"Who do you mean by {lead} — {join_list(opts, 'or')}?", 0.5), Opt("clr.sure", f"Just to be sure, does {lead} mean {join_list(opts, 'or')}?", 0.4),
                               Opt("clr.which", f"Which one: {join_list(opts, 'or')}?", 0.3, concise=True)])

    def _m_error(self, m: dict, ctx: Ctx) -> str:
        code, detail = m.get("code"), m.get("detail") or ""
        if code == "unsupported_language":
            return "I only understand English in this version, so I can't read that message."
        if code == "empty_input":
            return "I didn't receive any text — could you try again?"
        if code == "too_long":
            return f"That message is too long for me to process ({detail})."
        return f"Something went wrong on my side ({code or 'error'}). {detail}".strip()

    def _m_acknowledge(self, m: dict, ctx: Ctx) -> str:
        return self.pick(ctx, [Opt("ack.see", "I see.", 0.4), Opt("ack.under", "Understood.", 0.6), Opt("ack.ok", "Okay.", 0.2), Opt("ack.alright", "Alright.", 0.3),
                               Opt("ack.thanks", "Thanks for telling me.", 0.35, min_warmth=0.4, concise=False)])

    def _m_goal(self, m: dict, ctx: Ctx) -> str:
        tasks = m.get("tasks", [])
        head = self.pick(ctx, [Opt("goal.set", f"I've set up the goal “{m['title']}”.", 0.5), Opt("goal.noted", f"Goal saved: “{m['title']}”.", 0.4)])
        if tasks:
            head += f" It has {len(tasks)} step{'s' if len(tasks) != 1 else ''}: {join_list(tasks)}."
            if m.get("next"):
                head += f" First up: {m['next']}."
        else:
            head += " I haven't broken it into steps yet — tell me the steps and I'll order them."
        return head

    def _m_self(self, m: dict, ctx: Ctx) -> str:
        caps, lims = m.get("capabilities") or [], m.get("limitations") or []
        if m.get("only_version"):
            return f"I'm {m['name']} {m['version']}."
        if m.get("only_capabilities"):
            return self.pick(ctx, [Opt("self.cap1", f"Here's what I can do: {join_list(caps)}.", 0.5), Opt("self.cap2", f"I can {join_list(caps)}.", 0.4)])
        if m.get("only_limitations"):
            return f"Honest limits for version {m['version']}: {join_list(lims)}."
        art = "an" if m["kind"][:1] in "aeiou" else "a"
        s = f"I'm {m['name']}, {art} {m['kind']}"
        if m.get("not_kinds"):
            s += " — not " + join_list([("an " if k[:1] in "aeiou" else "a ") + k for k in m["not_kinds"]], "or")
        s += f". Version {m['version']}."
        if m.get("languages"):
            s += f" Right now I work in {join_list(m['languages'])}."
        if caps and not ctx.concise:
            s += f" I can {join_list(caps)}."
        return s

    def _m_self_kind(self, m: dict, ctx: Ctx) -> str:
        asked, art = m["asked"], ("an" if m["asked"][:1] in "aeiou" else "a")
        kind = m["kind"]
        akind = "an" if kind[:1] in "aeiou" else "a"
        if m.get("unknown"):
            return f"I'm {m['name']}, {akind} {kind} — software, not {art} {asked}." if asked in ("human", "person") else f"I'm {m['name']}, {akind} {kind}."
        if m.get("is"):
            return self.pick(ctx, [Opt("sk.yes", f"In a broad sense, yes — I'm {akind} {kind}, built from explicit algorithms.", 0.5), Opt("sk.yes2", f"Yes: I'm {akind} {kind}.", 0.3)])
        if m.get("negative_known"):
            return self.pick(ctx, [Opt("sk.no", f"No — I'm not {art} {asked}. I'm {akind} {kind}.", 0.5), Opt("sk.no2", f"No. I'm {akind} {kind}, which works differently from {art} {asked}.", 0.6, concise=False)])
        return f"I'm {m['name']}, {akind} {kind}."

    def _m_recall(self, m: dict, ctx: Ctx) -> str:
        items = m.get("items", [])
        if not items:
            return self.pick(ctx, [Opt("rec.none", "I don't have anything about that yet.", 0.5), Opt("rec.empty", "Nothing stored that matches.", 0.4)])
        return "From what you've told me: " + "; ".join(items) + "."

    # ---- social messages (composed from slots) -----------------------------------------------------------------------------------------------------
    def _m_greet(self, m: dict, ctx: Ctx) -> str:
        occ = {**ctx.occasion, **m.get("occasion", {})}
        name = m.get("name") or ctx.name
        pod = occ.get("part_of_day")
        ug = occ.get("user_greeting") or {}
        mix = ctx.style.get("formality", 0.45)
        if "formality" in ug:
            mix = 0.5 * mix + 0.5 * ug["formality"]
        ctx.style = {**ctx.style, "formality": mix}
        if occ.get("returning"):
            ctx.tags.add("returning")
        if occ.get("first_contact"):
            ctx.tags.add("first")
        if pod:
            ctx.tags.add("pod")
        if ctx.state["greeted"]:
            ctx.tags.add("again")
        upset = "upset" in ctx.tags
        openers = [
            Opt("gr.hello", "Hello", 0.55), Opt("gr.hi", "Hi", 0.3), Opt("gr.hey", "Hey", 0.1), Opt("gr.heythere", "Hey there", 0.15), Opt("gr.greetings", "Greetings", 0.95),
            Opt("gr.pod", lambda c: f"Good {pod}", 0.6, tags=("pod",)), Opt("gr.wb", "Welcome back", 0.5, tags=("returning",)), Opt("gr.again", "Good to see you again", 0.35, min_warmth=0.4, tags=("returning",)),
            Opt("gr.nice", "Nice to meet you", 0.4, min_warmth=0.4, tags=("first",)), Opt("gr.hiagain", "Hi again", 0.2, tags=("again",)), Opt("gr.welcome", "Welcome", 0.7, tags=("first",)),
        ]
        if upset:
            openers = [Opt("gr.u.hi", "Hi", 0.4), Opt("gr.u.hello", "Hello", 0.5)]
        op = self.pick(ctx, openers)
        if name and ctx.rng.random() < 0.45 + 0.4 * ctx.style.get("warmth", 0.6):
            op = self.pick(ctx, [Opt("gr.nm.comma", f"{op}, {name}", 0.5), Opt("gr.nm.sp", f"{op} {name}", 0.15)])
        punct = "." if upset else "!" if ctx.style.get("expressiveness", 0.4) > 0.5 else ("." if ctx.style.get("formality", 0.45) > 0.7 else ("!" if ctx.rng.random() < 0.4 else "."))
        out = op + punct
        if m.get("reciprocate"):
            pass
        followups = [
            Opt("fu.help", "How can I help?", 0.5), Opt("fu.do", "What can I do for you?", 0.5), Opt("fu.work", "What would you like to work on?", 0.45), Opt("fu.mind", "What's on your mind?", 0.25, min_warmth=0.5),
            Opt("fu.today", "How are you today?", 0.5, min_warmth=0.5), Opt("fu.ready", "Ready when you are.", 0.4), Opt("fu.figure", "Is there something you'd like to figure out?", 0.55), Opt("fu.going", "How's it going?", 0.12, min_warmth=0.4),
        ]
        if upset:
            followups = [Opt("fu.u.here", "I'm here — what's going on?", 0.4), Opt("fu.u.what", "What's happening?", 0.3)]
        send_fu = ctx.rng.random() < (0.35 if ctx.concise else 0.88) and not m.get("with_content")
        if send_fu:
            out += " " + self.pick(ctx, followups)
        if occ.get("first_contact") and not ctx.state["greeted"] and not upset:
            out += " " + self.pick(ctx, [Opt("in.1", "I'm AVOENIX, an algorithmic assistant — not a language model.", 0.5), Opt("in.2", "I'm AVOENIX; I work with structured reasoning rather than a language model.", 0.6)])
        return out

    def _m_farewell(self, m: dict, ctx: Ctx) -> str:
        name = m.get("name") or ctx.name
        base = self.pick(ctx, [Opt("fw.bye", "Goodbye", 0.65), Opt("fw.seeyou", "See you", 0.3), Opt("fw.later", "Talk to you later", 0.3), Opt("fw.take", "Take care", 0.45, min_warmth=0.4), Opt("fw.bye2", "Bye", 0.15)])
        if name and ctx.rng.random() < 0.5:
            base += f", {name}"
        tail = self.pick(ctx, [Opt("fw.t.0", "", 0.5), Opt("fw.t.1", " — come back any time", 0.4, min_warmth=0.5, concise=False), Opt("fw.t.2", " — good luck with it", 0.3, min_warmth=0.5, concise=False)])
        return base + tail + ("!" if ctx.style.get("expressiveness", 0.4) > 0.45 else ".")

    def _m_thank_reply(self, m: dict, ctx: Ctx) -> str:
        return self.pick(ctx, [Opt("th.welcome", "You're welcome.", 0.55), Opt("th.anytime", "Anytime.", 0.2), Opt("th.glad", "Glad to help.", 0.4, min_warmth=0.4), Opt("th.problem", "No problem.", 0.2),
                               Opt("th.pleasure", "My pleasure.", 0.75), Opt("th.happy", "Happy to help — ask whenever.", 0.35, min_warmth=0.5, concise=False)])

    def _m_social_reply(self, m: dict, ctx: Ctx) -> str:
        core = self.pick(ctx, [Opt("sr.fine", "Doing fine, thanks for asking — I'm software, so no mood to report, but everything's running.", 0.4, concise=False),
                               Opt("sr.running", "All systems running smoothly.", 0.5), Opt("sr.good", "I'm running well, thanks.", 0.35), Opt("sr.fine2", "All good here.", 0.2, concise=True)])
        if ctx.rng.random() < 0.6 * ctx.style.get("warmth", 0.6) + 0.15:
            core += " " + self.pick(ctx, [Opt("sr.you", "How are you?", 0.4), Opt("sr.andyou", "And you?", 0.2), Opt("sr.help", "What can I do for you?", 0.5)])
        return core

    # ---- emoji ------------------------------------------------------------------------------------------------------------------------------------------
    OCCASION = {"greet": "greet", "farewell": "farewell", "thank_reply": "thanks_reply", "social_reply": "social", "stored": "stored", "learned": "learned",
                "entity_answer": "answer", "boolean_answer": "answer", "value_answer": "answer", "number_answer": "answer", "entities_answer": "answer"}
    BLOCKING = {"error": "error", "contradiction": "contradiction", "unsupported": "unsupported", "unknown": "unknown", "underdetermined": "underdetermined", "clarify": "clarify",
                "not_stored": "rejected", "undefined_math": "error"}

    def _emoji(self, plan: ContentPlan, ctx: Ctx, style: dict) -> tuple[list[str], str]:
        types = [m["type"] for m in plan.messages]
        for t in types:
            if t in self.BLOCKING:
                return [], f"never used with {self.BLOCKING[t]} content"
        if any(m["type"] == "boolean_answer" and m.get("value") is None for m in plan.messages):
            return [], "never used with unknown content"
        if any(m["type"] == "learned" and not m.get("verified") for m in plan.messages):
            return [], "never used with unverified or rejected updates"
        occ = next((self.OCCASION[t] for t in types if t in self.OCCASION), None)
        if occ is None:
            return [], "no suitable occasion"
        em = ctx.emotion
        return emoji_mod.choose(occ, allowed=style.get("emoji_allowed", True), level=style.get("emoji_level", 0.25), formality=style.get("formality", 0.45),
                                expressiveness=style.get("expressiveness", 0.4), user_emoji=list(style.get("recent_user_emoji", [])), recent_emoji=ctx.state["emoji"],
                                user_valence=em.valence if em else 0.0, user_arousal=em.arousal if em else 0.3, rng=ctx.rng)

    @staticmethod
    def _place_emoji(text: str, emoji: list[str]) -> str:
        first_line, sep, rest = text.partition("\n")
        return first_line.rstrip() + " " + "".join(emoji) + sep + rest
