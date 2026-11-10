"""Shallow syntactic analysis: NP/VP/PP chunking and clause structure for English.

This is a deterministic, rule-based chunk parser. It recognises:

* noun phrases (determiners, numerals, adjectives, compounds, possessives, ``of`` complements,
  coordination, wh-phrases such as "how many apples");
* verb groups (auxiliaries, modals, negation, tense/aspect, passive voice, "going to" future);
* copular predicates including comparatives ("older than"), equatives ("as old as"),
  superlatives ("the youngest") and measure phrases ("30 years old");
* declarative, interrogative (yes/no and wh-) and imperative clauses;
* clause linkage by subordinators (because, if, when...), coordinators and commas, including
  verb-phrase coordination with a shared subject.

It is not a full grammar: relative clauses, deep embedding, gapping and many idioms are
outside scope and are reported through ``ParsedSentence.coverage`` and ``notes``.
"""

from __future__ import annotations

from .gazetteer import PLACES as _PLACES

from .lexicon import (
    ADVERBS_COMMON, AUX_BE, DEICTIC_DAYS, DETERMINERS, GRADABLE, INTERJECTIONS, MEASURE_ADJECTIVES, MODALS, MONTHS,
    NUMBER_WORDS, ORDINALS, PRONOUNS, SCALE_WORDS, SUBORDINATORS_CLAUSE, TIME_UNITS, UNITS, WEEKDAYS, WH_WORDS,
    INF_COMPLEMENT, VERBS,
)
from .syntax import AdjP, Clause, NP, PP, ParsedSentence, VG
from .tokenizer import Token

_NP_START = {"DET", "NUM", "ADJ", "NOUN", "PROPN", "PRON"}
_SUB_ROLE = {
    "because": "cause", "since": "cause_or_time", "if": "condition", "unless": "condition_negated", "when": "temporal_simultaneous",
    "while": "temporal_simultaneous", "although": "contrast", "though": "contrast", "whereas": "contrast",
    "after": "temporal_after", "before": "temporal_before", "until": "temporal_until", "once": "temporal_after",
    "whether": "condition",
}


class Parser:
    # ------------------------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------------------------
    def parse(self, tokens: list[Token], text: str, index: int = 0) -> ParsedSentence:
        words = [t for t in tokens if t.kind in ("word", "number", "abbr", "clitic", "time")]
        body = list(tokens)
        terminal = None
        while body and body[-1].kind == "punct" and body[-1].norm in (".", "!", "?", "...", ")", '"', "”"):
            if body[-1].norm in (".", "!", "?", "..."):
                terminal = body[-1].norm if terminal is None else terminal
            body.pop()
        while body and body[-1].kind == "emoji":
            body.pop()
        # leading discourse markers ("hello,", "oh", "well,") and trailing "please"
        markers: list[Token] = []
        while body and (body[0].pos == "INTJ" and not self._is_social_only(body)) or (body and body[0].norm in ("well", "so", "ok", "okay", "yes", "no", "oh", "hey", "hi", "hello") and len(body) > 1 and body[0].pos in ("INTJ", "ADV", "CCONJ", "DET")):
            if body[0].pos == "DET" and body[0].norm == "no" and len(body) > 1 and body[1].pos in ("NOUN", "ADJ"):
                break
            markers.append(body.pop(0))
            while body and body[0].kind == "punct" and body[0].norm == ",":
                body.pop(0)
        while markers and body and body[0].norm in ("there", "everyone", "all", "again") and (len(body) == 1 or body[1].norm == ","):
            body.pop(0)
            while body and body[0].kind == "punct" and body[0].norm == ",":
                body.pop(0)
        if body and body[-1].norm == "please" and len(body) > 1:
            markers.append(body.pop())
            while body and body[-1].kind == "punct" and body[-1].norm == ",":
                body.pop()
        if body and all(t.pos in ("INTJ", "PUNCT") or t.kind in ("punct", "emoji") for t in body) and any(t.pos == "INTJ" for t in body):
            markers += [t for t in body if t.pos == "INTJ"]
            body = []
        # leading additive conjunction on a fragment: "And Peter?" / "But the second one?"
        if len(body) > 1 and body[0].pos == "CCONJ" and body[0].norm in ("and", "but", "or") and body[1].pos not in ("VERB", "AUX"):
            markers.append(body.pop(0))
        vocative = None
        if len(body) > 2 and body[0].pos == "PROPN" and body[1].kind == "punct" and body[1].norm == ",":
            vocative = NP([body[0]], body[0], kind="name", span=(0, 1))
            body = body[2:]
        notes: list[str] = []
        clauses: list[Clause] = []
        if body:
            clauses = self._parse_body(body, terminal, notes)
        for k, c in enumerate(clauses):
            c.index = k
            c.sentence_index = index
        consumed = set()
        for c in clauses:
            for t in self._clause_tokens(c):
                consumed.add(t.i)
        for t in markers:
            consumed.add(t.i)
        if vocative:
            consumed.add(vocative.tokens[0].i)
        content = [t for t in words if t.i not in {tt.i for tt in markers if False}]
        coverage = (len([t for t in words if t.i in consumed]) / len(words)) if words else 1.0
        return ParsedSentence(tokens=tokens, text=text, clauses=clauses, discourse_markers=markers, vocative=vocative,
                              terminal=terminal, coverage=coverage, index=index, notes=notes)

    @staticmethod
    def _is_social_only(body: list[Token]) -> bool:
        return all(t.pos in ("INTJ", "PUNCT", "PROPN", "ADV") or t.norm in ("thank", "you", "very", "much", "so", "good", "morning", "evening", "afternoon", "night", "again", "there", "everyone", "all") for t in body)

    @staticmethod
    def _clause_tokens(c: Clause) -> list[Token]:
        out: list[Token] = []
        if c.subject and not c.inherited_subject:
            out += c.subject.tokens
        if c.vg:
            out += c.vg.tokens
        for np in c.objects:
            out += np.tokens
        comp = c.complement
        if comp is not None:
            out += comp.tokens if hasattr(comp, "tokens") else []
        for pp in c.pps:
            out += pp.tokens
        out += c.advs
        for np in c.time_nps:
            out += np.tokens
        if c.wh:
            out += c.wh.tokens
        if c.wh_adj:
            out.append(c.wh_adj)
        if c.question_kind == "ellipsis":
            out += [t for t in c.tokens if t.norm in ("what", "how", "about")]
        if c.infinitive:
            out += Parser._clause_tokens(c.infinitive)
        out += [t for t in c.tokens if t.norm in ("how", "where", "when", "why") and t.i < 3] if c.wh_adv else []
        out += [t for t in c.tokens if t.kind == "punct" or t.norm in (",",)]
        if c.connective:
            out += [t for t in c.tokens if t.norm == c.connective]
        return out

    # ------------------------------------------------------------------------------------
    # Clause segmentation
    # ------------------------------------------------------------------------------------
    def _parse_body(self, body: list[Token], terminal: str | None, notes: list[str]) -> list[Clause]:
        segments = self._segment(body)
        clauses: list[Clause] = []
        last_subject: NP | None = None
        for k, (conn, role, toks) in enumerate(segments):
            if not toks:
                continue
            clause = self._parse_clause(toks, terminal if k == 0 else None, notes, last_subject)
            clause.connective, clause.connective_role = conn, role
            if k == 0 and terminal == "?" and clause.mood == "declarative":
                clause.mood = "interrogative"          # rising-intonation question ("You like tea?")
                clause.question_kind = clause.question_kind or "yes_no"
            if clause.subject is not None:
                last_subject = clause.subject
            clauses.append(clause)
        return clauses

    def _segment(self, toks: list[Token]) -> list[tuple[str | None, str | None, list[Token]]]:
        """Split into (connective, role, tokens) segments. Subordinate clauses keep their order."""
        n = len(toks)
        cuts: list[tuple[int, int, str | None, str | None]] = []   # (cut_start, content_start, connective, role)
        i = 1 if n else 0
        while i < n:
            t = toks[i]
            at_start = False
            if t.pos == "SCONJ" and t.norm in SUBORDINATORS_CLAUSE and self._clause_starts(toks, i + 1):
                cuts.append((i, i + 1, t.norm, _SUB_ROLE.get(t.norm, "subordinate")))
            elif t.pos == "SCONJ" and t.norm == "that" and i > 0 and toks[i - 1].pos in ("VERB",) and self._clause_starts(toks, i + 1):
                cuts.append((i, i + 1, "that", "complement"))
            elif t.pos == "SCONJ" and t.norm == "so" and self._clause_starts(toks, i + 1):
                cuts.append((i, i + 1, "so", "result"))
            elif t.pos == "CCONJ" and t.norm in ("and", "but", "or", "so", "yet") and (self._clause_starts(toks, i + 1) or self._vp_follows(toks, i + 1, i)):
                role = {"and": "coordinate", "but": "contrast", "or": "alternative", "so": "result", "yet": "contrast"}[t.norm]
                cuts.append((i, i + 1, t.norm, role))
            elif t.kind == "punct" and t.norm == "," and i + 1 < n and (self._clause_starts(toks, i + 1) or toks[i + 1].pos in ("CCONJ",) and self._clause_starts(toks, i + 2)):
                # a comma before a new clause; a following coordinator is handled by its own cut
                if toks[i + 1].pos != "CCONJ" and toks[i + 1].pos != "SCONJ":
                    cuts.append((i, i + 1, None, "juxtaposed"))
            i += 1
        # leading subordinator ("If it rains, we stay.")
        leading: tuple[str | None, str | None] = (None, None)
        start = 0
        if toks and toks[0].pos == "SCONJ" and toks[0].norm in SUBORDINATORS_CLAUSE and toks[0].norm not in ("that",):
            leading = (toks[0].norm, _SUB_ROLE.get(toks[0].norm, "subordinate"))
            start = 1
        segments: list[tuple[str | None, str | None, list[Token]]] = []
        cur_start, cur_conn = start, leading
        for cut_start, content_start, conn, role in cuts:
            if cut_start < cur_start:
                continue
            seg = [t for t in toks[cur_start:cut_start] if not (t.kind == "punct" and t.norm == ",")]
            if seg:
                segments.append((cur_conn[0], cur_conn[1], seg))
            cur_start, cur_conn = content_start, (conn, role)
        seg = [t for t in toks[cur_start:] if not (t.kind == "punct" and t.norm == ",")] if cur_start >= start else []
        if seg:
            segments.append((cur_conn[0], cur_conn[1], seg))
        if not segments:
            segments.append((None, None, [t for t in toks if not (t.kind == "punct" and t.norm == ",")]))
        # "If A, B": the later (main) clause is first in importance; keep textual order, parser consumers use roles
        return segments

    @staticmethod
    def _clause_starts(toks: list[Token], j: int) -> bool:
        """Does a (subject NP +) verb group begin at position j?"""
        n = len(toks)
        k = j
        while k < n and toks[k].pos in ("DET", "ADJ", "NUM", "NOUN", "PROPN", "PRON", "POSS") and not (toks[k].pos == "PRON" and toks[k].norm in ("what", "who", "which") and False):
            k += 1
        if k == j:
            return False
        while k < n and toks[k].pos in ("ADV", "PART"):
            k += 1
        return k < n and toks[k].pos in ("VERB", "AUX")

    @staticmethod
    def _vp_follows(toks: list[Token], j: int, conn_index: int) -> bool:
        """VP coordination: 'Sarah opened the door and walked in' (shared subject)."""
        k = j
        n = len(toks)
        while k < n and toks[k].pos in ("ADV", "PART"):
            k += 1
        if not (k < n and toks[k].pos == "VERB"):
            return False
        # there must be a verb before the connective already (so this is a second predicate)
        return any(t.pos == "VERB" or (t.pos == "AUX" and t.feats.get("aux") != "modal") for t in toks[:conn_index])

    # ------------------------------------------------------------------------------------
    # Clause parsing
    # ------------------------------------------------------------------------------------
    def _parse_clause(self, toks: list[Token], terminal: str | None, notes: list[str], last_subject: NP | None) -> Clause:
        c = Clause(tokens=toks, span=(toks[0].i, toks[-1].i))
        n = len(toks)
        i = 0
        # ---- fronted wh-phrase -------------------------------------------------------------
        wh_np: NP | None = None
        if toks[0].norm in WH_WORDS or (toks[0].norm in ("what", "which", "whose") and toks[0].pos in ("DET", "PRON")):
            w = toks[0].norm
            if w in ("who", "whom") or (w == "what" and (n == 1 or toks[1].pos in ("AUX", "VERB", "ADP", "ADV"))) or (w == "which" and (n == 1 or toks[1].pos in ("AUX", "VERB"))):
                wh_np = NP([toks[0]], toks[0], kind="wh", wh=w, definite=False, pron_features=dict(PRONOUNS.get(w, {})), span=(toks[0].i, toks[0].i))
                i = 1
            elif w in ("what", "which", "whose"):
                np, j = self._parse_np(toks, 0)
                if np:
                    np.kind, np.wh = "wh", w
                    wh_np, i = np, j
            elif w == "how" and n > 2 and toks[1].norm in ("many", "much"):
                np, j = self._parse_np(toks, 2)
                if np is None:
                    np, j = NP([], None, elided_head=True, span=(toks[0].i, toks[1].i)), 2
                np.kind, np.wh = "wh", "how_" + toks[1].norm
                np.tokens = toks[:2] + np.tokens
                wh_np, i = np, j
            elif w == "how" and n > 2 and toks[1].pos in ("ADJ", "ADV") and toks[1].pos != "AUX":
                c.wh_adv, c.wh_adj, i = "how_adj", toks[1], 2
            elif w in ("where", "when", "why", "how"):
                c.wh_adv, i = w, 1
        c.wh = wh_np
        # "What about X?" / "How about X?": elliptical question about X
        if n >= 3 and toks[0].norm in ("what", "how") and toks[1].norm == "about" and wh_np is not None or (n >= 3 and toks[0].norm in ("what", "how") and toks[1].norm == "about"):
            np, k = self._parse_np_coord(toks, 2)
            if np is not None:
                c.mood, c.question_kind, c.subject, c.wh, c.wh_adv = "interrogative", "ellipsis", np, None, None
                c.wh_adv = None
                return c
        # ---- verb group / subject identification ---------------------------------------------
        if i < n and toks[i].pos == "AUX" and (wh_np is not None or c.wh_adv or toks[i].feats.get("aux") in ("be", "do", "have", "modal")):
            self._parse_inverted(c, toks, i, wh_np, terminal)
        elif wh_np is not None and i < n and toks[i].pos == "VERB":
            # wh-subject: "Who gave Michael a book?"
            c.mood, c.question_kind = "interrogative", "wh_subject"
            c.subject = wh_np
            vg, j = self._parse_vg(toks, i)
            c.vg = vg
            self._parse_rest(c, toks, j)
        elif wh_np is not None and i >= n:
            c.mood, c.question_kind = "interrogative", "wh_bare"
            c.subject = wh_np
        elif toks[0].pos == "VERB" and toks[0].feats.get("form") == "base" and wh_np is None and not c.wh_adv and not self._subject_before_verb(toks):
            c.mood = "imperative"
            vg, j = self._parse_vg(toks, 0)
            c.vg = vg
            self._parse_rest(c, toks, j)
        else:
            self._parse_declarative(c, toks, i, last_subject, notes)
        if c.mood == "declarative" and terminal == "?":
            c.mood = "interrogative"
            c.question_kind = c.question_kind or "yes_no"
        self._extract_time_and_infinitive(c)
        return c

    @staticmethod
    def _subject_before_verb(toks: list[Token]) -> bool:
        return len(toks) > 1 and toks[0].pos == "VERB" and toks[1].pos == "VERB"

    def _parse_declarative(self, c: Clause, toks: list[Token], i: int, last_subject: NP | None, notes: list[str]) -> None:
        n = len(toks)
        # leading adverbials ("Yesterday, Sarah gave...")
        lead: list[Token] = []
        while i < n and toks[i].pos == "ADV" and not (i + 1 < n and toks[i + 1].pos in ("VERB", "AUX") and self._no_np_before(toks, i)):
            lead.append(toks[i])
            i += 1
        c.advs += lead
        subj, j = self._parse_np_coord(toks, i)
        if subj is not None and j < n and toks[j].pos in ("AUX", "VERB", "ADV", "PART"):
            c.subject = subj
            vg, k = self._parse_vg(toks, j)
            c.vg = vg
            self._parse_rest(c, toks, k)
            return
        if subj is None and i < n and toks[i].pos in ("VERB", "AUX"):
            # shared-subject VP coordination ("... and walked in")
            c.subject = last_subject
            c.inherited_subject = last_subject is not None
            vg, k = self._parse_vg(toks, i)
            c.vg = vg
            self._parse_rest(c, toks, k)
            return
        if subj is not None and j >= n:
            c.subject = subj                   # fragment ("Paris", "my name") - no predicate
            c.leftovers = []
            notes.append("fragment: noun phrase without predicate")
            return
        # unparsable: keep everything as leftovers
        c.leftovers = toks[i:]
        if subj is not None:
            c.subject = subj
            c.leftovers = toks[j:]
        notes.append("could not find a verb group")

    @staticmethod
    def _no_np_before(toks: list[Token], i: int) -> bool:
        return not any(t.pos in ("NOUN", "PROPN", "PRON") for t in toks[:i])

    def _parse_inverted(self, c: Clause, toks: list[Token], i: int, wh_np: NP | None, terminal: str | None) -> None:
        n = len(toks)
        aux_group: list[Token] = []
        j = i
        # collect leading auxiliaries up to (but not including) the subject NP
        while j < n and toks[j].pos == "AUX":
            aux_group.append(toks[j])
            j += 1
        # negation attached to the first aux ("Isn't Paris...") is tokenised as AUX n't
        while j < n and toks[j].pos == "PART" and toks[j].norm == "not":
            aux_group.append(toks[j])
            j += 1
        first_aux = aux_group[0]
        kind = first_aux.feats.get("aux")
        # is there a verb directly after the aux group? then the wh-phrase is the subject (no inversion)
        if wh_np is not None and j < n and (toks[j].pos == "VERB" or (toks[j].pos == "ADV" and j + 1 < n and toks[j + 1].pos == "VERB")):
            c.mood, c.question_kind = "interrogative", "wh_subject"
            c.subject = wh_np
            vg, k = self._parse_vg(toks, i)
            c.vg = vg
            self._parse_rest(c, toks, k)
            return
        subj, k = self._parse_np_coord(toks, j)
        if wh_np is not None and kind == "be" and (subj is None or k >= n or toks[k].pos in ("PUNCT",)):
            # "What is the capital of France?" / "Who is the youngest?" / "Who is Sarah?"
            c.mood, c.question_kind = "interrogative", "wh_identify"
            c.subject = wh_np
            vg, _ = self._parse_vg(toks, i)
            vg.copula = True
            vg.tokens = aux_group
            c.vg = vg
            c.complement = subj if subj is not None else self._parse_adjp(toks, j)[0]
            if c.complement is None and j < n:
                adjp, _ = self._parse_adjp(toks, j)
                c.complement = adjp
            return
        if wh_np is not None and kind == "be" and subj is None:
            adjp, k2 = self._parse_adjp(toks, j)
            if adjp:
                c.mood, c.question_kind = "interrogative", "wh_identify"
                c.subject, c.complement = wh_np, adjp
                vg = VG(tokens=aux_group, main=None, auxes=aux_group, copula=True, lemma="be",
                        tense="past" if first_aux.feats.get("form") == "past" else "present")
                c.vg = vg
                return
        if subj is None:
            c.leftovers = toks[j:]
            return
        c.mood = "interrogative"
        c.question_kind = "yes_no" if wh_np is None and not c.wh_adv else (
            "wh_object" if wh_np is not None else "wh_adjunct" if c.wh_adv != "how_adj" else "wh_degree")
        if c.wh_adv == "how_adj":
            c.question_kind = "wh_degree"
        c.subject = subj
        # rebuild the verb group: leading aux(es) + whatever verb follows the subject
        vg_tokens = list(aux_group)
        main: Token | None = None
        adverbs: list[Token] = []
        m = k
        while m < n and (toks[m].pos in ("ADV", "PART", "AUX")) and not (toks[m].pos == "ADV" and m + 1 < n and toks[m + 1].pos not in ("VERB", "AUX", "PART")):
            vg_tokens.append(toks[m])
            if toks[m].pos == "ADV":
                adverbs.append(toks[m])
            m += 1
        if m < n and toks[m].pos == "VERB":
            main = toks[m]
            vg_tokens.append(main)
            m += 1
        vg = self._build_vg(vg_tokens, main, [t for t in vg_tokens if t.pos == "AUX"], adverbs)
        if main is None and kind == "be":
            vg.copula = True
        c.vg = vg
        self._parse_rest(c, toks, m)

    # ---- verb group ------------------------------------------------------------------------
    def _parse_vg(self, toks: list[Token], i: int) -> tuple[VG, int]:
        n = len(toks)
        vg_tokens: list[Token] = []
        auxes: list[Token] = []
        adverbs: list[Token] = []
        main: Token | None = None
        j = i
        while j < n:
            t = toks[j]
            if t.pos == "AUX":
                auxes.append(t)
                vg_tokens.append(t)
                j += 1
            elif t.pos == "PART" and t.norm == "not":
                vg_tokens.append(t)
                j += 1
            elif t.pos == "ADV" and j + 1 < n and toks[j + 1].pos in ("VERB", "AUX", "PART") and (auxes or vg_tokens):
                adverbs.append(t)
                vg_tokens.append(t)
                j += 1
            elif t.pos == "VERB":
                main = t
                vg_tokens.append(t)
                j += 1
                break
            else:
                break
        # "is going to VERB" -> future
        vg = self._build_vg(vg_tokens, main, auxes, adverbs)
        if main is not None and main.lemma == "go" and main.feats.get("form") == "gerund" and j + 1 < n and toks[j].norm == "to" \
                and toks[j].pos == "PART" and toks[j + 1].pos == "VERB":
            vg.tense, vg.aspect = "future", None
            vg_tokens += [toks[j], toks[j + 1]]
            vg.main = toks[j + 1]
            vg.lemma = toks[j + 1].lemma
            vg.tokens = vg_tokens
            j += 2
        # phrasal particle ("give up", "pick up")
        if vg.main is not None and j < n and toks[j].pos == "ADP" and toks[j].norm in ("up", "down", "off", "out") and not (j + 1 < n and toks[j + 1].pos in ("DET", "NOUN", "PROPN") and toks[j].norm == "off" and False):
            vg.particle = toks[j]
            vg.tokens = vg.tokens + [toks[j]]
            j += 1
        return vg, j

    def _build_vg(self, vg_tokens: list[Token], main: Token | None, auxes: list[Token], adverbs: list[Token]) -> VG:
        neg = any(t.norm == "not" and t.pos == "PART" for t in vg_tokens)
        be_forms = [a for a in auxes if a.feats.get("aux") == "be"]
        have_forms = [a for a in auxes if a.feats.get("aux") == "have"]
        modals = [a for a in auxes if a.feats.get("aux") == "modal"]
        do_forms = [a for a in auxes if a.feats.get("aux") == "do"]
        first_aux = auxes[0] if auxes else None
        tense = "present"
        aspect: str | None = None
        voice = "active"
        modal: str | None = None
        main_form = main.feats.get("form") if main else None
        if modals:
            modal = modals[0].lemma
            tense = "future" if modal in ("will", "shall") else ("past" if modal in ("could", "might") and False else "present")
            if modal == "would":
                tense = "present"
        if first_aux is not None and not modals:
            form = first_aux.feats.get("form")
            tense = "past" if form == "past" else "present"
        elif main is not None and not auxes:
            tense = "past" if main_form == "past" else "present"
        if have_forms and main_form in ("participle", "past") and not be_forms[:0]:
            aspect = "perfect"
            if any(a.norm in ("been",) for a in be_forms) and main_form == "gerund":
                aspect = "perfect_progressive"
        if be_forms and main is not None:
            if main_form == "gerund":
                aspect = "progressive" if aspect is None else "perfect_progressive"
            elif main_form in ("participle", "past") and not any(a.feats.get("aux") == "have" for a in auxes if a is be_forms[0]) and (len(be_forms) >= 1):
                # be + participle => passive (unless 'have' + participle only)
                voice = "passive"
                aspect = "perfect" if have_forms else aspect
        copula = main is None and bool(be_forms)
        lemma = main.lemma if main else ("be" if be_forms else (first_aux.lemma if first_aux else ""))
        if main is None and not be_forms and have_forms:
            lemma = "have"
        if be_forms and main is not None and main_form == "gerund" and not have_forms and not modals:
            pass
        if tense == "present" and not modals and be_forms and any(a.norm in ("was", "were") for a in be_forms):
            tense = "past"
        span = (vg_tokens[0].i, vg_tokens[-1].i) if vg_tokens else (0, 0)
        return VG(tokens=vg_tokens, main=main, auxes=auxes, neg=neg, tense=tense, aspect=aspect, voice=voice, modal=modal,
                  copula=copula, lemma=lemma, adverbs=adverbs, span=span)

    # ---- everything after the verb group -----------------------------------------------------
    def _parse_rest(self, c: Clause, toks: list[Token], j: int) -> None:
        n = len(toks)
        vg = c.vg
        copular = bool(vg and (vg.copula or (vg.main and VERBS.get(vg.main.lemma, ("", ""))[1] == "copula_like")))
        # copular predicate: ADJP / NP / PP
        if copular:
            # skip adverbs ("is very tall", "is not as old as")
            k = j
            while k < n and toks[k].pos == "PART" and toks[k].norm == "not":
                if vg:
                    vg.neg = True
                    vg.tokens.append(toks[k])
                k += 1
            adjp, k2 = self._parse_adjp(toks, k)
            if adjp is not None and not (adjp.degree == "sup" and k2 < n and toks[k2].pos in ("NOUN",)):
                c.complement = adjp
                j = k2
            else:
                np, k2 = self._parse_np_coord(toks, k)
                if np is not None and not (np.kind == "common" and np.head is None and np.superlative is None and not np.adjs and np.number is None):
                    c.complement = np
                    j = k2
                elif k < n and toks[k].pos == "ADP":
                    pp, k2 = self._parse_pp(toks, k)
                    if pp:
                        c.complement = pp
                        j = k2
        # generic argument/adjunct loop
        while j < n:
            t = toks[j]
            if t.pos == "PUNCT":
                j += 1
                continue
            if t.pos == "ADP" or (t.pos == "SCONJ" and False):
                pp, k = self._parse_pp(toks, j)
                if pp is not None:
                    c.pps.append(pp)
                    j = k
                    continue
            if t.pos == "PART" and t.norm == "to" and j + 1 < n and toks[j + 1].pos == "VERB":
                inf, k = self._parse_infinitive(toks, j)
                c.infinitive = inf
                j = k
                continue
            if t.pos in _NP_START or t.pos == "POSS":
                np, k = self._parse_np_coord(toks, j, post_verbal=True)
                if np is not None:
                    c.objects.append(np)
                    j = k
                    continue
            if t.pos == "ADV":
                c.advs.append(t)
                j += 1
                continue
            if t.pos == "PART" and t.norm == "not":
                if vg:
                    vg.neg = True
                j += 1
                continue
            if t.pos == "ADJ" and c.objects == [] and c.complement is None and vg and vg.main is not None:
                adjp, k = self._parse_adjp(toks, j)       # "makes him happy", "looks tired"
                if adjp:
                    c.complement = adjp
                    j = k
                    continue
            c.leftovers.append(t)
            j += 1

    def _parse_infinitive(self, toks: list[Token], j: int) -> tuple[Clause, int]:
        n = len(toks)
        start = j
        j += 1  # 'to'
        inf = Clause(tokens=[], mood="infinitive")
        vg_toks = [toks[j]]
        vg = self._build_vg(vg_toks, toks[j], [], [])
        vg.tokens = [toks[start], toks[j]]
        inf.vg = vg
        j += 1
        sub = Clause(tokens=toks[j:])
        sub.vg = vg
        self._parse_rest(sub, toks, j)
        inf.objects, inf.pps, inf.advs, inf.complement, inf.leftovers = sub.objects, sub.pps, sub.advs, sub.complement, sub.leftovers
        inf.tokens = toks[start:]
        inf.span = (toks[start].i, toks[-1].i)
        return inf, n

    def _extract_time_and_infinitive(self, c: Clause) -> None:
        """Move temporal NPs/adverbs/PPs into ``time_nps`` / ``advs`` handling in the semantic layer."""
        keep: list[NP] = []
        for np in c.objects:
            if np.kind == "time":
                c.time_nps.append(np)
            else:
                keep.append(np)
        c.objects = keep

    # ------------------------------------------------------------------------------------
    # Phrase chunkers
    # ------------------------------------------------------------------------------------
    def _parse_pp(self, toks: list[Token], j: int) -> tuple[PP | None, int]:
        n = len(toks)
        prep = toks[j]
        k = j + 1
        np, k2 = self._parse_np_coord(toks, k)
        if np is None:
            # gerund object ("by giving a book") or stranded preposition
            if k < n and toks[k].pos == "VERB" and toks[k].feats.get("form") == "gerund":
                return PP(prep, None, [prep, toks[k]], span=(prep.i, toks[k].i)), k + 1
            return PP(prep, None, [prep], span=(prep.i, prep.i), stranded=True), k
        return PP(prep, np, [prep] + np.tokens, span=(prep.i, np.span[1])), k2

    def _parse_np_coord(self, toks: list[Token], j: int, post_verbal: bool = False) -> tuple[NP | None, int]:
        np, k = self._parse_np(toks, j)
        if np is None:
            return None, j
        members = [np]
        coord = None
        n = len(toks)
        while k < n and ((toks[k].pos == "CCONJ" and toks[k].norm in ("and", "or")) or (toks[k].kind == "punct" and toks[k].norm == ",")):
            nxt, k2 = self._parse_np(toks, k + 1)
            if nxt is None or nxt.kind == "wh":
                break
            # post-verbal "and <NP> <VERB>" starts a new clause rather than extending the list
            if post_verbal and k2 < n and toks[k2].pos in ("VERB", "AUX"):
                break
            # a comma only coordinates when a coordinator or another comma follows (a, b and c)
            if toks[k].kind == "punct" and not (k2 < n and (toks[k2].pos == "CCONJ" or toks[k2].norm == ",")) and not (k2 >= n or toks[k2].pos in ("PUNCT", "VERB", "AUX") and False):
                if not (k2 < n and toks[k2].pos == "CCONJ"):
                    break
            if toks[k].kind == "word":
                coord = toks[k].norm
            members.append(nxt)
            k = k2
        if len(members) == 1:
            return np, k
        allt: list[Token] = []
        for idx, m in enumerate(members):
            allt += m.tokens
            if idx < len(members) - 1:
                allt.append(toks[members[idx].span[1] + 1] if members[idx].span[1] + 1 < len(toks) + toks[0].i else m.tokens[-1])
        tokens_span = [t for t in toks if members[0].span[0] <= t.i <= members[-1].span[1]]
        group = NP(tokens_span, None, kind="group", members=members, coord=coord or "and", plural=True,
                   span=(members[0].span[0], members[-1].span[1]))
        return group, k

    def _parse_np(self, toks: list[Token], j: int) -> tuple[NP | None, int]:
        n = len(toks)
        if j >= n:
            return None, j
        start = j
        t = toks[j]
        # wh determiner phrases are parsed by the caller; treat bare wh pronouns as NPs here
        if t.pos == "PRON" and t.norm in ("who", "whom"):
            return NP([t], t, kind="wh", wh=t.norm, pron_features=dict(PRONOUNS[t.norm]), span=(t.i, t.i)), j + 1
        if t.pos == "PRON" and t.norm not in ("one", "ones"):
            np = NP([t], t, kind="pron", pron_features=dict(t.feats), plural=t.feats.get("number") == "pl", span=(t.i, t.i), definite=True)
            return np, j + 1
        det: Token | None = None
        quant: str | None = None
        definite: bool | None = None
        number: float | None = None
        adjs: list[Token] = []
        nouns: list[Token] = []
        possessor: NP | None = None
        poss_marker = False
        # predeterminer + determiner
        while j < n and toks[j].pos == "DET":
            d = toks[j]
            if d.feats.get("quant"):
                quant = d.feats["quant"]
            if d.feats.get("definite") is not None:
                definite = d.feats["definite"]
            if d.feats.get("poss"):
                definite = True
                possessor = NP([d], d, kind="pron", pron_features={k: v for k, v in d.feats.items() if k not in ("poss",)}, span=(d.i, d.i), definite=True)
            det = d if det is None or d.feats.get("definite") is not None else det
            j += 1
            if j - start > 2:
                break
        # numerals (digits or words, incl. "twenty five", "two hundred")
        if j < n and toks[j].pos == "NUM":
            number, j = self._parse_number(toks, j)
        # adjectives (possibly modified by intensifiers)
        while j < n and (toks[j].pos == "ADJ" or (toks[j].pos == "ADV" and j + 1 < n and toks[j + 1].pos == "ADJ" and toks[j].norm in ADVERBS_COMMON)):
            if toks[j].pos == "ADV":
                j += 1
                continue
            # a predicative comparative/superlative with no noun stays outside the NP unless a det licenses nominalisation
            adjs.append(toks[j])
            j += 1
        # nouns / proper nouns (with 's possessors)
        while j < n and (toks[j].pos in ("NOUN", "PROPN") or (toks[j].pos == "POSS" and nouns)):
            if toks[j].pos == "POSS":
                owner_tokens = nouns[:]
                possessor = NP(owner_tokens, owner_tokens[-1], kind="name" if owner_tokens[-1].pos == "PROPN" else "common",
                               span=(owner_tokens[0].i, owner_tokens[-1].i), definite=True)
                nouns = []
                adjs = []
                poss_marker = True
                j += 1
                # possessed head may carry its own adjectives
                while j < n and toks[j].pos == "ADJ":
                    adjs.append(toks[j]); j += 1
                continue
            # two adjacent well-known place names are two names, not one ("the capital of Kenya Nairobi")
            if nouns and nouns[-1].pos == "PROPN" and toks[j].pos == "PROPN" and nouns[-1].norm in _PLACES and toks[j].norm in _PLACES:
                break
            nouns.append(toks[j])
            j += 1
        # one-anaphora: "that one", "the first one", "the other ones"
        if not nouns and j < n and toks[j].norm in ("one", "ones") and toks[j].pos in ("PRON", "NUM") and (det is not None or adjs):
            one = toks[j]
            j += 1
            return NP(tokens=toks[start:j], head=one, det=det, adjs=adjs, kind="one_anaphor", definite=True,
                      plural=one.norm == "ones", span=(toks[start].i, toks[j - 1].i)), j
        head: Token | None = nouns[-1] if nouns else None
        elided = False
        superlative: Token | None = None
        kind = "common"
        if head is None:
            if number is not None:
                elided = True
                kind = "num"
            elif adjs and (det is not None or quant) and adjs[-1].feats.get("degree") in ("sup", "cmp"):
                superlative = adjs.pop()
                kind = "nominal_adj"
            elif adjs and det is not None and adjs[-1].norm in ("poor", "rich", "young", "old", "dead", "living", "wealthy", "homeless", "sick"):
                kind = "nominal_adj"
                superlative = None
            elif adjs and toks[j - 1].pos == "ADJ" and j - 1 >= start and det is not None:
                kind = "nominal_adj"
            else:
                return None, start
        elif head.pos == "PROPN":
            kind = "name"
        head_lemma = head.lemma if head else None
        if head is not None and head.lemma in TIME_UNITS and (det is not None and det.norm in ("last", "next", "this", "every", "each") or any(a.norm in ("last", "next", "previous", "this") for a in adjs) or number is not None):
            kind = "time"
        if head is not None and head.norm in WEEKDAYS + MONTHS:
            kind = "time" if head.norm in WEEKDAYS or head.norm in MONTHS else kind
        if head is not None and head.norm in ("morning", "afternoon", "evening", "night") and (det is not None and det.norm in ("this", "that", "every", "last") or any(a.norm in ("last", "next") for a in adjs)):
            kind = "time"
        # "last week", "next month": 'last'/'next' are ADJ in the lexicon so they land in adjs
        measure_unit = None
        if head is not None and (head.norm in UNITS or head.lemma in UNITS) and number is not None:
            measure_unit = UNITS.get(head.norm, UNITS.get(head.lemma, (None,)))[0]
        plural = bool(head and head.feats.get("number") == "pl") or (number is not None and number != 1) or quant in ("all", "most", "many", "few", "some") and bool(head and head.feats.get("number") == "pl")
        np = NP(tokens=toks[start:j], head=head, det=det, quant=quant, number=number, adjs=adjs, modifiers=nouns[:-1],
                kind=kind, definite=definite if definite is not None else (True if kind == "name" else None),
                plural=plural, elided_head=elided, measure_unit=measure_unit, possessor=possessor, superlative=superlative,
                possessive_marker=poss_marker, span=(toks[start].i, toks[j - 1].i))
        # "of" complement ("the capital of France", "a cup of tea")
        if j + 1 < n and toks[j].pos == "ADP" and toks[j].norm == "of" and kind != "time":
            of_np, k = self._parse_np_coord(toks, j + 1)
            if of_np is not None:
                np.of_np = of_np
                np.tokens = toks[start:k]
                np.span = (toks[start].i, toks[k - 1].i)
                j = k
        return np, j

    def _parse_number(self, toks: list[Token], j: int) -> tuple[float | None, int]:
        n = len(toks)
        t = toks[j]
        if t.kind == "number":
            return t.value, j + 1
        total = 0.0
        current = 0.0
        seen = False
        k = j
        while k < n and (toks[k].norm in NUMBER_WORDS or toks[k].norm in SCALE_WORDS or (toks[k].norm == "and" and seen and k + 1 < n and toks[k + 1].norm in NUMBER_WORDS and False)
                         or (toks[k].norm == "-")):
            w = toks[k].norm
            if w in NUMBER_WORDS:
                if w == "dozen":
                    current = (current or 1) * 12
                elif w == "half":
                    current += 0.5
                else:
                    current += NUMBER_WORDS[w]
                seen = True
            elif w in SCALE_WORDS:
                scale = SCALE_WORDS[w]
                if scale == 100:
                    current = (current or 1) * 100
                else:
                    total += (current or 1) * scale
                    current = 0
                seen = True
            k += 1
        if not seen:
            return None, j
        return total + current, k

    # ---- adjective phrases -----------------------------------------------------------------------
    def _parse_adjp(self, toks: list[Token], j: int) -> tuple[AdjP | None, int]:
        n = len(toks)
        start = j
        measure: NP | None = None
        intens: list[Token] = []
        # measure phrase: "30 years old", "1.8 meters tall"
        if j < n and toks[j].pos == "NUM":
            np, k = self._parse_np(toks, j)
            if np is not None and k < n and toks[k].pos == "ADJ" and toks[k].lemma in MEASURE_ADJECTIVES and np.measure_unit:
                measure = np
                j = k
        # "not" after copula for equatives is handled by the caller
        periphrastic = None
        if j < n and toks[j].norm in ("more", "less", "most", "least") and j + 1 < n and toks[j + 1].pos == "ADJ":
            periphrastic = toks[j].norm
            j += 1
        equative = False
        if j < n and toks[j].norm == "as" and j + 1 < n and toks[j + 1].pos in ("ADJ",):
            equative = True
            j += 1
        while j < n and toks[j].pos == "ADV" and j + 1 < n and (toks[j + 1].pos == "ADJ" or toks[j + 1].norm == "as"):
            intens.append(toks[j])
            j += 1
        if j < n and toks[j].norm == "as" and j + 1 < n and toks[j + 1].pos == "ADJ" and not equative:
            equative = True
            j += 1
        if j >= n or toks[j].pos != "ADJ":
            return None, start
        adj = toks[j]
        base = adj.lemma
        degree = adj.feats.get("degree", "pos")
        if periphrastic in ("more", "less"):
            degree = "cmp"
        elif periphrastic in ("most", "least"):
            degree = "sup"
        j += 1
        standard: NP | None = None
        if equative and j + 1 < n and toks[j].norm == "as":
            standard, k = self._parse_np_coord(toks, j + 1)
            j = k if standard is not None else j + 1
        elif degree == "cmp" and j < n and toks[j].norm == "than":
            standard, k = self._parse_np_coord(toks, j + 1)
            if standard is not None:
                j = k
        elif degree == "sup" and j + 1 < n and toks[j].norm in ("of", "in", "among") and toks[j].pos == "ADP":
            standard, k = self._parse_np_coord(toks, j + 1)
            if standard is not None:
                j = k
        return AdjP(adj=adj, base=base, degree=degree, standard=standard, equative=equative, periphrastic=periphrastic,
                    intensifiers=intens, measure=measure, tokens=toks[start:j], span=(toks[start].i, toks[j - 1].i)), j
