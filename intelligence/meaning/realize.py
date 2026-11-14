"""Language realisation from meaning: a grammar that builds clauses from structure and inflects them, with variation chosen by an n-gram ranker.

The realiser never stores a reply. It receives *communicative acts* (acknowledge, answer, unknown, ask-slot, calculation, deduction, attribution,
clarification) with the concepts they carry, and builds sentences from:

* a clause grammar (subject, verb lemma, tense, polarity, complements) with a small morphology generator (do-support, -s/-ed/-ing, irregulars);
* referring-expression choice (pronoun when the entity was just mentioned, noun phrase otherwise, "you/your" for the speaker);
* discourse components (uptake opener, content clause, justification tail, follow-up question) that are selected from the act's features
  (novelty, valence, certainty, provenance) and combined;
* alternative constructions for the same content (word order / lexical choice from the concept cluster), ranked by a smoothed trigram model
  trained on ``data/realiser_corpus.txt`` and sampled with a seeded RNG so the same input + seed reproduces the same reply.

The language model here is a *ranking prior*, trained on a tiny developer-written corpus; it removes clumsy candidates and breaks ties. It does
not generate text. Quality limits are documented in the technical report.
"""
from __future__ import annotations

import math
import random
import re
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "data"
IRREGULAR = {"be": ("is", "was", "being", "are"), "have": ("has", "had", "having", "have"), "do": ("does", "did", "doing", "do"), "go": ("goes", "went", "going", "go"),
             "buy": ("buys", "bought", "buying", "buy"), "get": ("gets", "got", "getting", "get"), "make": ("makes", "made", "making", "make"), "say": ("says", "said", "saying", "say"),
             "tell": ("tells", "told", "telling", "tell"), "lose": ("loses", "lost", "losing", "lose"), "spend": ("spends", "spent", "spending", "spend"), "give": ("gives", "gave", "giving", "give"),
             "pay": ("pays", "paid", "paying", "pay"), "work": ("works", "worked", "working", "work"), "live": ("lives", "lived", "living", "live"), "move": ("moves", "moved", "moving", "move")}
NUMBER_WORDS = {}


def tokenize(s: str) -> list[str]:
    return re.findall(r"[a-z']+|[0-9]+|[.,?!]", s.lower())


class NgramLM:
    """Interpolated trigram/bigram/unigram model with add-k smoothing; ``score`` is the mean log-probability per token (length-normalised)."""

    def __init__(self, k: float = 0.1):
        self.k = k
        self.uni: Counter = Counter()
        self.bi: Counter = Counter()
        self.tri: Counter = Counter()
        self.ctx_bi: Counter = Counter()
        self.ctx_tri: Counter = Counter()
        self.vocab: set[str] = set()

    def train(self, sentences: list[str]) -> "NgramLM":
        for s in sentences:
            toks = ["<s>", "<s>"] + tokenize(s) + ["</s>"]
            self.vocab.update(toks)
            for i in range(2, len(toks)):
                self.uni[toks[i]] += 1
                self.bi[(toks[i - 1], toks[i])] += 1
                self.tri[(toks[i - 2], toks[i - 1], toks[i])] += 1
                self.ctx_bi[toks[i - 1]] += 1
                self.ctx_tri[(toks[i - 2], toks[i - 1])] += 1
        self.total = sum(self.uni.values())
        return self

    def prob(self, w2: str, w1: str, w: str) -> float:
        V = len(self.vocab) + 1
        p1 = (self.uni[w] + self.k) / (self.total + self.k * V)
        p2 = (self.bi[(w1, w)] + self.k * V * p1) / (self.ctx_bi[w1] + self.k * V) if self.ctx_bi[w1] else p1
        p3 = (self.tri[(w2, w1, w)] + self.k * V * p2) / (self.ctx_tri[(w2, w1)] + self.k * V) if self.ctx_tri[(w2, w1)] else p2
        return 0.6 * p3 + 0.3 * p2 + 0.1 * p1

    def score(self, sentence: str) -> float:
        toks = ["<s>", "<s>"] + tokenize(sentence) + ["</s>"]
        lp = sum(math.log(self.prob(toks[i - 2], toks[i - 1], toks[i])) for i in range(2, len(toks)))
        return lp / max(1, len(toks) - 2)


@lru_cache(maxsize=1)
def default_lm() -> NgramLM:
    lines = [l.strip() for l in (DATA / "realiser_corpus.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    return NgramLM().train(lines)


# ---- morphology -------------------------------------------------------------------------------------------------------------------------
def inflect(verb: str, tense: str = "present", person: int = 3, number: str = "singular", form: str = "finite") -> str:
    irr = IRREGULAR.get(verb)
    if form == "gerund":
        return irr[2] if irr else (verb[:-1] + "ing" if verb.endswith("e") and not verb.endswith("ee") else verb + "ing")
    if form == "base":
        return verb
    if verb == "be":
        if tense == "past":
            return "were" if (number == "plural" or person == 2) else ("was" if True else "were")
        return {1: "am", 2: "are"}.get(person, "are" if number == "plural" else "is")
    if tense == "past":
        if irr:
            return irr[1]
        if verb.endswith("e"):
            return verb + "d"
        if re.search(r"[^aeiou]y$", verb):
            return verb[:-1] + "ied"
        return verb + "ed"
    if person == 3 and number == "singular":
        if irr:
            return irr[0]
        if re.search(r"(s|sh|ch|x|z|o)$", verb):
            return verb + "es"
        if re.search(r"[^aeiou]y$", verb):
            return verb[:-1] + "ies"
        return verb + "s"
    return irr[3] if irr else verb


def plural(noun: str, n=2) -> str:
    if n == 1:
        return noun
    if noun.endswith("ey") or noun.endswith("ay") or noun.endswith("oy"):
        return noun + "s"
    if re.search(r"[^aeiou]y$", noun):
        return noun[:-1] + "ies"
    if re.search(r"(s|sh|ch|x|z)$", noun):
        return noun + "es"
    return noun + "s"


def clause(subject: str, verb: str, *, tense: str = "present", neg: bool = False, person: int = 3, number: str = "singular", complements: list[str] | None = None,
           contract: bool = False, aux: str | None = None) -> str:
    """Build one finite clause with correct agreement and do-support."""
    comps = " ".join(c for c in (complements or []) if c)
    if verb == "be":
        v = inflect("be", tense, person, number)
        if neg:
            v = (v + "n't") if contract and v in ("is", "are", "was", "were") else v + " not"
        return f"{subject} {v} {comps}".strip()
    if aux:
        v = f"{aux} {'not ' if neg else ''}{verb}"
        return f"{subject} {v} {comps}".strip()
    if neg:
        d = inflect("do", tense, person, number)
        v = f"{d}n't" if contract else f"{d} not"
        return f"{subject} {v} {verb} {comps}".strip()
    return f"{subject} {inflect(verb, tense, person, number)} {comps}".strip()


def cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def finish(s: str, q: bool = False) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    s = cap(s)
    return s if s[-1:] in ".?!" else s + ("?" if q else ".")


class Realizer:
    def __init__(self, lm: NgramLM | None = None, seed: int | None = None):
        self.lm = lm or default_lm()
        self.rng = random.Random(seed)
        self.choices: list[dict] = []

    # ---- selection --------------------------------------------------------------------------------------------------------------------------
    def choose(self, label: str, candidates: list[str], recent: list[str] | None = None) -> str:
        """Rank grammatical candidates by LM score, penalise recent repeats, sample from the top group (softmax with a low temperature)."""
        cands = [c for c in dict.fromkeys(candidates) if c]
        if len(cands) == 1:
            self.choices.append({"slot": label, "options": 1})
            return cands[0]
        scored = []
        for c in cands:
            s = self.lm.score(finish(c))
            if recent and any(c.lower().strip(" .,") == r.lower().strip(" .,") for r in recent):
                s -= 3.0
            scored.append((s, c))
        best = max(s for s, _ in scored)
        weights = [math.exp((s - best) / 0.6) for s, _ in scored]
        pick = self.rng.choices([c for _, c in scored], weights=weights, k=1)[0]
        self.choices.append({"slot": label, "options": len(cands), "picked": pick, "scores": {c: round(s, 2) for s, c in scored}})
        return pick


# ======================================================================================================================================
# Communicative acts -> text
# ======================================================================================================================================
def art(noun: str) -> str:
    if not noun:
        return noun
    return ("an " if noun[0].lower() in "aeiou" else "a ") + noun


OPENERS = {
    "new": ["Got it", "Noted", "Okay", "Thanks for telling me", "Good to know", "Understood", "I see"],
    "new_neg": ["Sorry to hear that", "That sounds tough", "I'm sorry about that", "That sounds hard"],
    "repeat": ["Right, you mentioned that", "Yes, I already had that", "I have that already"],
    "revised": ["Okay, I've updated that", "Thanks for the correction", "Got it, I've changed that", "Understood, I've replaced the earlier detail"],
}


class ActRealizer(Realizer):
    """Turns an ordered list of act dicts (see ``intelligence.meaning.engine``) into reply text; ``self.choices`` records each decision."""

    # -- referring expressions -----------------------------------------------------------------------------------------------------------------
    def subj(self, ref: dict, *, answering: bool = True) -> tuple[str, int, str, str]:
        """(subject text, person, number, possessive) for an agent reference."""
        if ref.get("kind") == "self":
            return "you", 2, "singular", "your"
        label = ref.get("label") or "it"
        if ref.get("pron_ok") and ref.get("gender") in ("male", "female"):
            return ("he" if ref["gender"] == "male" else "she"), 3, "singular", ("his" if ref["gender"] == "male" else "her")
        if ref.get("person") is False and ref.get("pron_ok"):
            return "it", 3, "singular", "its"
        return label, 3, "singular", label + "'s"

    # -- frame clauses ---------------------------------------------------------------------------------------------------------------------
    def frame_clauses(self, a: dict) -> list[str]:
        fr = a["frame"]
        s, pn, num, poss = self.subj(a.get("agent", {"kind": "self"}))
        neg = a.get("polarity") == "negative"
        tense = a.get("tense") if a.get("tense") in ("past",) else "present"
        val = a.get("value")
        time = a.get("time")
        tail = f" {time}" if time and time in ("now", "today", "right now", "at the moment", "currently") else ""
        out: list[str] = []
        if fr == "residence":
            out.append(clause(s, "live", person=pn, number=num, neg=neg, complements=[f"in {val}"]) + tail)
            if not neg and tense == "present":
                out.append(f"{poss} home is in {val}" if pn == 2 else f"{s} is based in {val}")
                if pn == 2:
                    out.append(f"{val} is where you live")
            if a.get("construction") == "V" and a.get("verb_lemma") in ("move", "relocate") or tense == "past" and a.get("moved"):
                out = [clause(s, "move", tense="past", person=pn, number=num, neg=neg, complements=[f"to {val}"])]
        elif fr == "occupation":
            out.append(clause(s, "work", person=pn, number=num, neg=neg, complements=[f"as {art(val)}"]))
            out.append(clause(s, "be", person=pn, number=num, neg=neg, complements=[art(val)]))
        elif fr == "naming":
            if pn == 2:
                out += [f"your name is {val}", f"you go by {val}", f"you are called {val}"] if not neg else [f"your name is not {val}"]
            else:
                out += [clause(s, "be", person=pn, complements=[f"called {val}"], neg=neg), f"{poss} name is {val}"]
        elif fr == "acquisition":
            thing = val
            verb = a.get("verb_lemma") if a.get("verb_lemma") in ("buy", "get", "purchase", "order") else "buy"
            verbs = [verb] + (["get"] if verb == "buy" else [])
            for v in verbs:
                out.append(clause(s, v, tense="past" if a.get("tense") == "past" else "present", person=pn, number=num, neg=neg, complements=[art(thing) if not thing.startswith(("a ", "an ", "your ")) else thing]) + (f" {time}" if time else ""))
        elif fr == "purpose":
            it = a.get("thing_np", "it")
            out.append(clause(s, "use", person=pn, number=num, neg=neg, complements=[it, f"for {val}"]))
            out.append(f"{it} is for {val}" if not neg else f"{it} is not for {val}")
        elif fr == "maker":
            it = a.get("thing_np", "it")
            if a.get("inferred"):
                out += [f"{val} makes {it}, going by the model name", f"{it} looks like a {val} product, going by the model name"]
            else:
                out += [f"{val} makes {it}", f"{it} is made by {val}"]
        elif fr == "preference":
            verb = a.get("verb_lemma") or "like"
            if verb not in ("like", "love", "enjoy", "hate", "dislike", "prefer", "adore"):
                verb = "like"
            out.append(clause(s, verb, person=pn, number=num, neg=neg, complements=[val]))
            if neg and verb in ("like", "love", "enjoy"):
                out.append(clause(s, "dislike" if pn == 2 else "dislike", person=pn, number=num, complements=[val]))
        elif fr == "consumption":
            verb = a.get("verb_lemma") if a.get("verb_lemma") in ("drink", "eat", "have", "consume") else "drink"
            out.append(clause(s, verb, person=pn, number=num, neg=neg, complements=[val]) + (f" {time}" if time else ""))
        elif fr == "age":
            be = inflect("be", "present", pn, num)
            out += [f"{s} {be} {val} years old", f"{s} {be} {val}"] if not neg else [f"{s} {be} not {val}"]
            if not neg and pn == 2:
                out.append(f"your age is {val}")
        elif fr == "funds":
            if val == "insufficient":
                be = inflect("be", "present", pn, num)
                out += [f"{s} {be} short on money{tail}", f"money is tight for {'you' if pn == 2 else s}{tail}",
                        clause(s, "have", neg=True, person=pn, number=num, complements=["enough money"]) + tail]
            else:
                out += [clause(s, "have", person=pn, number=num, complements=["enough money"]) + tail, clause(s, "can", person=pn, number=num, complements=["afford it"]) if False else f"{s} can afford it{tail}"]
        return out

    def ask_clause(self, a: dict) -> list[str]:
        fr, role = a["frame"], a.get("role") or a["frame"]
        s, pn, num, poss = self.subj(a.get("agent", {"kind": "self"}))
        if fr == "residence":
            return [f"Where {'do' if pn == 2 or num == 'plural' else 'does'} {s} live?"]
        if fr == "occupation":
            return [f"What {'do' if pn == 2 else 'does'} {s} do for a living?", f"What {'do' if pn == 2 else 'does'} {s} do?"]
        if fr == "naming":
            return [f"What is {poss} name?", f"What should I call {s}?"]
        if fr == "purpose":
            return [f"What {'do' if pn == 2 else 'does'} {s} use {a.get('thing_np', 'it')} for?"]
        return [f"What is {poss} {role}?"]

    # -- act renderers ---------------------------------------------------------------------------------------------------------------------
    def render(self, acts: list[dict], recent: list[str] | None = None) -> str:
        sentences: list[str] = []
        for a in acts:
            fn = getattr(self, "act_" + a["type"], None)
            if fn is None:
                continue
            sentences += fn(a, recent or [])
        return " ".join(sentences).strip()

    def act_ack(self, a: dict, recent: list[str]) -> list[str]:
        if a.get("slot_fill"):
            v, thing = a["value"], a.get("thing_np", "it")
            if a["slot_fill"] == "model":
                forms = [f"{cap(art(v)) if not v[:1].isupper() else 'A ' + v if False else v}? Nice", f"So {thing} is {art(v) if not v.split()[0][:1].isupper() else 'a ' + v}", f"Got it, {thing} is {art(v) if not v.split()[0][:1].isupper() else 'a ' + v}", f"Nice, a {v}"]
            elif a["slot_fill"] == "use":
                forms = [f"Okay, so you use {thing} for {v}", f"{cap(v)} — good to know", f"Got it, {thing} is for {v}", f"Nice, {v}"]
            else:
                forms = [f"Got it, {thing} is called {v}", f"Okay, {v}"]
            return [finish(self.choose("slot-ack", forms, recent))]
        content = self.frame_clauses(a)
        if not content:
            return [self.choose("ack-generic", ["Got it.", "Noted.", "Understood."], recent)]
        body = self.choose("ack-content", content, recent)
        key = "revised" if a.get("novelty") == "revised" else "repeat" if a.get("novelty") == "repeat" else "new_neg" if a.get("valence", 0) < 0 else "new"
        opener = self.choose("ack-opener", OPENERS[key], recent)
        forms = [f"{opener}. {cap(body)}.", f"{opener}, {body}.", f"{cap(body)}, {opener[:1].lower() + opener[1:]}." if key in ("new",) else f"{opener}. {cap(body)}."]
        if key == "revised" and a.get("old") is not None:
            forms.append(f"{opener}: {body}, not {a['old']}.")
        if key == "new_neg":
            forms = [f"{opener}. {cap(body)}.", f"{opener}, {body}."]
        return [self.choose("ack-form", [finish(f) for f in forms], recent)]

    def act_answer(self, a: dict, recent: list[str]) -> list[str]:
        base = self.frame_clauses(a)
        if not base:
            return [finish(str(a.get("value", "")))]
        stmt = self.choose("answer-content", base, recent)
        forms = [finish(stmt)]
        if a.get("source") == "told":
            forms += [finish(f"you told me that {stmt}"), finish(f"as far as you've told me, {stmt}")]
        if a.get("yn") == "yes":
            forms = [finish(f"yes, {stmt}"), finish(f"yes — {stmt}"), finish(stmt)]
        elif a.get("yn") == "no":
            forms = [finish(f"no, {stmt}")]
        if a.get("uncertain"):
            forms = [finish(f"I believe {stmt}"), finish(f"as far as I know, {stmt}")]
        return [self.choose("answer-form", forms, recent)]

    def act_negative_answer(self, a: dict, recent: list[str]) -> list[str]:
        return self.act_answer({**a, "polarity": "negative", "yn": "no" if a.get("yn") else None}, recent)

    def act_prefs(self, a: dict, recent: list[str]) -> list[str]:
        def join(xs):
            return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]
        out = []
        if a.get("likes"):
            out.append(finish(self.choose("prefs-like", [f"You've told me you like {join(a['likes'])}", f"So far you like {join(a['likes'])}",
                                                            f"From what you've said, you like {join(a['likes'])}"], recent)))
        if a.get("dislikes"):
            lead = "But you" if out else "You"
            out.append(finish(f"{lead} avoid or dislike {join(a['dislikes'])}"))
        return out

    def act_unknown(self, a: dict, recent: list[str]) -> list[str]:
        s, pn, num, poss = self.subj(a.get("agent", {"kind": "self"}))
        what = {"residence": f"where {s} {'live' if pn == 2 else 'lives'}", "occupation": f"what {s} {'do' if pn == 2 else 'does'} for a living", "naming": f"{poss} name",
                "purpose": f"what {'you use' if a.get('agent', {}).get('kind') == 'self' else 'it is used for'}", "maker": "who makes it", "funds": f"how {poss} money situation stands",
                "preference": "that", "consumption": "that", "age": f"how old {s} {'are' if pn == 2 else 'is'}"}.get(a["frame"], "that")
        forms = [f"I don't know {what} yet", f"You haven't told me {what} yet", f"I don't have {what} yet"]
        first = self.choose("unknown-lead", forms, recent)
        follow = []
        if a.get("agent", {}).get("kind") == "self" and a["frame"] in ("residence", "occupation", "naming", "purpose"):
            follow = [q for q in self.ask_clause(a)]
        out = [finish(first)]
        if follow:
            out.append(finish(self.choose("unknown-ask", follow, recent), q=True))
        return out

    def act_ask_slot(self, a: dict, recent: list[str]) -> list[str]:
        slot, thing = a["slot"], a.get("thing", "it")
        echo = a.get("echo_verb") if a.get("echo_verb") in ("buy", "get", "order", "purchase") else "get"
        if slot == "model":
            forms = [f"What model is {thing}?", f"Which model did you {echo}?", f"What model is it exactly?", f"Do you know which model {thing} is?"]
        elif slot == "use":
            forms = [f"What do you mainly use {thing} for?", f"What will you use {thing} for?", f"What do you use {thing} for?"]
        elif slot == "name":
            forms = [f"What is {thing} called?", f"What's its name?"]
        else:
            forms = [f"What is its {slot}?"]
        return [finish(self.choose("ask-" + slot, forms, recent), q=True)]

    def act_calc(self, a: dict, recent: list[str]) -> list[str]:
        v, u, kind = a["text_value"], a.get("unit") or "", a["kind"]
        un = plural(u, 2) if u and a.get("value_n", 2) != 1 else u
        subj = a.get("subject", "")
        if kind == "remaining":
            who = "you" if subj in ("i", "you") else cap(subj) if subj else "That"
            have = "have" if who == "you" else "has"
            forms = [f"{who} {have} {v} {un} left", f"That leaves {who.lower() if who == 'you' else who} with {v} {un}", f"{v} {un} remain"] if a.get("adv") == "left" else \
                    [f"{who} {have} {v} {un} now", f"{who} now {have} {v} {un}", f"That makes {v} {un} for {who.lower() if who == 'you' else who}"]
        elif kind == "total_cost":
            forms = [f"That comes to {v} {un} in total", f"You pay {v} {un} altogether", f"The total is {v} {un}"]
        elif kind == "distance":
            forms = [f"It goes {v} {un}", f"That's {v} {un}", f"It covers {v} {un} in that time"]
        elif kind == "container":
            forms = [f"There are {v} {un} in total", f"That gives {v} {un} altogether", f"{v} {un} fit in all of them"]
        else:
            forms = [f"The answer is {v} {un}"]
        out = [finish(self.choose("calc", forms, recent))]
        if a.get("steps") and a.get("explain"):
            out.append(finish("Working: " + "; ".join(a["steps"])))
        return out

    def act_deduce(self, a: dict, recent: list[str]) -> list[str]:
        ans, trace = a["answer"], a.get("trace", [])
        because = "; ".join(trace)
        if ans == "yes":
            forms = [f"Yes, because {because}", f"Yes — {because}", f"Yes. That follows: {because}"] if because else ["Yes."]
        elif ans == "no":
            forms = [f"No, because {because}", f"No — {because}"] if because else ["No."]
        elif ans == "inconsistent":
            forms = [f"Those statements contradict each other: {because}", f"Something doesn't add up: {because}"]
        else:
            forms = ["That doesn't follow from what you've told me", "Nothing you've told me settles that", "I can't tell from what you've said, so I won't guess"]
        return [finish(self.choose("deduce", forms, recent))]

    def act_report(self, a: dict, recent: list[str]) -> list[str]:
        src, claim = a["source"], a["claim"]
        verb = a.get("verb", "say")
        you = src == "you"
        attribution = [f"{cap(src)} {inflect(verb, 'present', 2 if you else 3)} {claim}"] if not you else [f"You {verb if verb in ('think','believe') else 'say'} {claim}"]
        verdicts = []
        status = a.get("status")
        if status == "conflict":
            known = a.get("known")
            verdicts = [f"that conflicts with what I know ({known})", f"I couldn't verify that, and it conflicts with what I know ({known})", f"it doesn't match what I hold ({known})"]
            tails = ["so I've kept it as a claim, not a fact", "so I'm treating it as unverified"]
        elif status == "unverified":
            verdicts = ["I couldn't verify that", "I have nothing to check that against"]
            tails = ["so I've recorded it as a claim, not a fact", "so I'm treating it as unverified for now"]
        else:
            verdicts = ["that matches what I know"]
            tails = ["so I've recorded it"]
        v = self.choose("report-verdict", verdicts, recent)
        t = self.choose("report-tail", tails, recent)
        head = self.choose("report-attrib", attribution, recent)
        forms = [f"{head}. {cap(v)}, {t}.", f"{head}, but {v}, {t}.", f"Noted: {head[:1].lower() + head[1:]}. {cap(v)}, {t}."]
        return [self.choose("report-form", [finish(f) for f in forms], recent)]

    def act_clarify(self, a: dict, recent: list[str]) -> list[str]:
        opts = a.get("options") or []
        if len(opts) >= 2:
            joined = " or ".join(opts[:3])
            forms = [f"Which one do you mean, {joined}?", f"Do you mean {joined}?"]
        else:
            forms = [f"What does '{a.get('surface', 'it')}' refer to?", f"I'm not sure what '{a.get('surface', 'it')}' refers to. Could you say which one you mean?"]
        return [finish(self.choose("clarify", forms, recent), q=True)]

    def act_confirm_revision(self, a: dict, recent: list[str]) -> list[str]:
        return self.act_ack({**a, "novelty": "revised"}, recent)

    def act_apology_miss(self, a: dict, recent: list[str]) -> list[str]:
        return [self.choose("miss", ["I didn't catch that. Could you say it a different way?", "I'm not sure I understood that. Could you rephrase it?"], recent)]

    def act_ack_rule(self, a: dict, recent: list[str]) -> list[str]:
        learned = a.get("learned") or []
        body = "; ".join(learned[:3])
        forms = [f"Understood: {body}", f"Got it — {body}", f"Okay, I'll work with that: {body}"]
        return [finish(self.choose("ack-rule", forms, recent))]

    def act_partial(self, a: dict, recent: list[str]) -> list[str]:
        t = " / ".join(a.get("text", [])[:2])
        forms = [f"I didn't follow the part about \"{t}\"", f"I couldn't make sense of \"{t}\" yet"]
        return [finish(self.choose("partial", forms, recent))]

    def act_plan(self, a: dict, recent: list[str]) -> list[str]:
        days = a.get("days")
        head = self.choose("plan-head", [f"Here is one way to {a['goal']} for the {a['object']}" + (f" in {days} day{'s' if days != 1 else ''}" if days else ""),
                                          f"A workable plan to {a['goal']} for the {a['object']}" + (f" over {days} day{'s' if days != 1 else ''}" if days else "") + " is below"], recent)
        lines = [f"{i}. {w} — {t}." for i, (w, t) in enumerate(a["steps"], 1)]
        return [finish(head) .replace(".", ":", 1) if False else head + ":", " ".join(lines)]
