"""English semantic construction: parsed clauses -> ACR.

General mechanisms (not per-sentence rules):

* Verb lemmas map to language-neutral action concepts; synonyms share one concept id.
* Grammatical functions map to semantic roles through the concept's argument frame
  (dative alternation, passive voice, cognitive verbs with experiencers...).
* Prepositions map to roles/slots (location, source, recipient, purpose...).
* Copular clauses are interpreted by predicate type: comparison -> ``rel.exceeds`` over a
  *dimension*, equative -> ``rel.equal_on``, superlative -> ``rel.extreme``, measure -> property
  with a Quantity, class membership -> ``rel.is_a``, attribute-of -> ``attr.<noun>``.
* Questions become an Intention that contains the same structures with ``Variable`` nodes for the
  unknowns, so asking and asserting share one representation.
* Pronouns become ``Reference`` nodes with agreement features; resolving them is the Context Engine's job.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ....representation import ACRBuilder, ACRDocument, Provenance, concepts
from . import gazetteer, lexicon as L
from .morphology import singularize
from .syntax import AdjP, Clause, NP, PP, ParsedSentence, VG
from .tokenizer import Token

PREP_ROLE = {
    "to": "goal", "from": "source", "in": "location", "at": "location", "on": "location", "inside": "location",
    "near": "location", "with": "comitative", "about": "topic", "of": "topic", "into": "goal", "onto": "goal",
    "toward": "goal", "towards": "goal", "through": "path", "over": "location", "under": "location", "behind": "location",
    "between": "location", "around": "location", "across": "location", "by": "instrument", "for": "purpose",
    "as": "attribute", "like": "manner", "without": "comitative_neg", "during": "time_ref", "after": "time_ref",
    "before": "time_ref", "since": "time_ref", "until": "time_ref", "per": "measure",
}
SOCIAL_FOCUS = {"you": "addressee_state"}
ORDINAL_HEADS = {"option", "choice", "one", "item", "answer", "suggestion", "idea", "result", "point", "alternative", "example", "step"}
ORDINAL_ADJ = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "last": -1, "final": -1, "previous": -2,
               "next": 2, "other": 0, "earlier": -2, "latter": -1, "former": 1}


class SemanticBuilder:
    def __init__(self, sentences: list[ParsedSentence], *, now: datetime | None, text: str,
                 provenance_method: str = "language.en"):
        self.sentences = sentences
        self.now = now
        self.text = text
        self.b = ACRBuilder(default_provenance=Provenance("user_statement", method=provenance_method))
        self.names: dict[str, str] = {}
        self.lemma_ent: dict[str, str] = {}
        self.speaker_id: str | None = None
        self.addressee_id: str | None = None
        self.ambiguity: list[dict] = []
        self.warnings: list[str] = []
        self.sent_idx = 0
        self._last_event: str | None = None

    # ------------------------------------------------------------------------------------------
    # Deixis
    # ------------------------------------------------------------------------------------------
    def speaker(self) -> str:
        if self.speaker_id is None:
            self.speaker_id = self.b.entity("speaker", "class.person", features={"animacy": "animate", "person": 1, "number": "sg"},
                                            annotations={"deixis": "speaker"})
        return self.speaker_id

    def addressee(self) -> str:
        if self.addressee_id is None:
            self.addressee_id = self.b.entity("AVOENIX", "class.entity", features={"animacy": "animate", "person": 2, "number": "sg"},
                                              annotations={"deixis": "addressee"})
        return self.addressee_id

    def _surface(self, np: NP | Token, gram: str | None = None) -> dict:
        start = np.span[0] if isinstance(np, NP) else np.i
        return {"surface": {"s": self.sent_idx, "i": start, "gram": gram}}

    # ------------------------------------------------------------------------------------------
    # Noun phrases
    # ------------------------------------------------------------------------------------------
    @staticmethod
    def _classify(lemma: str) -> tuple[str, str]:
        if lemma in L.PERSON_NOUNS or lemma in L.MALE_KIN or lemma in L.FEMALE_KIN:
            return "class.person", "animate"
        if lemma in L.ANIMAL_NOUNS:
            return "class.animal", "animate"
        if lemma in L.PLACE_NOUNS:
            return "class.place", "inanimate"
        if lemma in L.ABSTRACT_NOUNS:
            return "class.abstract", "inanimate"
        return "class.thing", "inanimate"

    def np_node(self, np: NP | None, gram: str | None = None, *, generic_ok: bool = True) -> str | None:
        if np is None:
            return None
        if np.kind == "group":
            members = [self.np_node(m, gram) for m in np.members]
            members = [m for m in members if m]
            return self.b.logical(np.coord or "and", members)
        if np.kind == "pron":
            return self._pronoun(np, gram)
        if np.kind == "wh":
            return self._wh_variable(np)
        if np.kind == "time":
            return self._time_np(np)
        if np.kind == "num" or np.elided_head:
            return self.b.reference("ellipsis", features={"number": np.number, "plural": np.number != 1 if np.number is not None else None},
                                    annotations={**self._surface(np, gram), "quantity": np.number})
        if np.kind == "one_anaphor":
            return self._one_anaphor(np, gram)
        if np.head is not None and np.kind == "common" and np.head.lemma in ORDINAL_HEADS and any(a.norm in ORDINAL_ADJ for a in np.adjs):
            return self._one_anaphor(np, gram)
        if np.kind == "nominal_adj":
            adj = np.superlative or (np.adjs[-1] if np.adjs else None)
            return self.b.concept(f"kind.{adj.lemma}_people" if adj else "kind.unknown", adj.lemma if adj else None)
        head = np.head
        assert head is not None
        owner_id = self.np_node(np.possessor, gram) if np.possessor is not None else None
        # names ---------------------------------------------------------------------------------
        if np.kind == "name":
            label = " ".join(t.text for t in (np.modifiers + [head]))
            key = label.lower()
            if key in self.names:
                return self.names[key]
            gender = head.feats.get("gender")
            if key in gazetteer.PLACES:
                et, feats = "class.place", {"animacy": "inanimate", "number": "sg"}
            elif gender:
                et, feats = "class.person", {"animacy": "animate", "gender": gender, "number": "sg"}
            else:
                et, feats = "class.entity", {"number": "sg", "animacy": "unknown"}
            nid = self.b.entity(label, et, features=feats, annotations=self._surface(np, gram))
            self.names[key] = nid
            return nid
        # common nouns ----------------------------------------------------------------------------
        lemma = head.lemma
        et, animacy = self._classify(lemma)
        plural = np.plural or head.feats.get("number") == "pl"
        bare_plural = np.det is None and np.quant is None and np.number is None and plural and not np.possessor
        quantified = np.quant in ("all", "most", "few", "some", "no", "any", "many") and plural
        every_sg = np.quant == "all" and not plural
        if generic_ok and (bare_plural or quantified or every_sg) and not np.adjs:
            return self.b.concept(f"kind.{lemma}", lemma, annotations={**self._surface(np, gram), "plural": plural,
                                                                          "quantifier": np.quant or "generic", "animacy": animacy})
        features: dict[str, Any] = {"animacy": animacy, "number": "pl" if plural else "sg", "lemma": lemma,
                                    "definite": bool(np.definite), "adjectives": [a.lemma for a in np.adjs]}
        if lemma in L.MALE_KIN:
            features["gender"] = "m"
        elif lemma in L.FEMALE_KIN:
            features["gender"] = "f"
        if np.number is not None:
            features["count"] = np.number
        key = f"{lemma}|{'|'.join(features['adjectives'])}"
        if np.definite and not np.possessor and key in self.lemma_ent:
            return self.lemma_ent[key]
        label = " ".join([*(a.text for a in np.adjs), *(m.text for m in np.modifiers), head.text])
        nid = self.b.entity(label.lower() if not head.text[:1].isupper() else label, et, features=features,
                            annotations=self._surface(np, gram))
        if np.definite or np.det is not None and np.det.norm in ("the",):
            self.lemma_ent[key] = nid
        if owner_id:
            self.b.proposition("rel.owns", {"owner": owner_id, "owned": nid}, confidence=0.9,
                               annotations={"origin": "possessive"})
        if np.of_np is not None:
            of_node = self.np_node(np.of_np, gram, generic_ok=False)
            if of_node:
                self.b.doc.nodes[nid].annotations["of"] = of_node
                self.b.doc.nodes[nid].annotations["relation"] = lemma
        return nid

    def _one_anaphor(self, np: NP, gram: str | None) -> str:
        ords = [a.norm for a in np.adjs if a.norm in ORDINAL_ADJ]
        feats: dict[str, Any] = {"plural": np.plural, "head": np.head.lemma if np.head else None}
        if ords:
            feats["ordinal"] = ORDINAL_ADJ[ords[0]]
            rtype = "ordinal"
        elif np.det is not None and np.det.norm in ("this", "that", "these", "those"):
            feats["deictic"] = "near" if np.det.norm in ("this", "these") else "far"
            rtype = "demonstrative"
        else:
            rtype = "definite"
        return self.b.reference(rtype, features=feats, annotations={**self._surface(np, gram), "word": np.text.lower()})

    def _pronoun(self, np: NP, gram: str | None) -> str:
        f = np.pron_features
        p, num = f.get("person"), f.get("number")
        h = np.head.norm if np.head else ""
        if p == 1 and num != "pl":
            return self.speaker()
        if p == 2:
            return self.addressee()
        feats = {k: v for k, v in f.items() if k in ("gender", "number", "animacy", "case", "person", "deictic", "generic", "indefinite", "quant")}
        if f.get("indefinite") or f.get("quant"):
            return self.b.concept("kind.someone" if f.get("animacy") == "animate" else "kind.something", h,
                                  annotations={"pronoun": h, **self._surface(np, gram), "quantifier": f.get("quant", "some")})
        if f.get("case") == "refl":
            return self.b.reference("reflexive", features=feats, annotations={**self._surface(np, gram), "word": h})
        rt = "demonstrative" if f.get("deictic") else "pronoun"
        return self.b.reference(rt, features=feats, annotations={**self._surface(np, gram), "word": h})

    def _wh_variable(self, np: NP) -> str:
        w = np.wh or "what"
        constraints: dict[str, Any] = {"wh": w}
        if w in ("who", "whom"):
            constraints["animacy"] = "animate"
        if w.startswith("how_"):
            constraints["quantity"] = True
        if np.head is not None:
            constraints["class"] = np.head.lemma
        return self.b.variable(w, **constraints)

    def _time_np(self, np: NP) -> str:
        head = np.head
        kw = {}
        mods = [a.norm for a in np.adjs] + ([np.det.norm] if np.det else [])
        gran = L.TIME_UNITS.get(head.lemma, None) if head else None
        if head and head.norm in L.WEEKDAYS:
            kw = dict(time_kind="recurrent" if np.plural else "instant", granularity="day", value=head.norm)
            if "last" in mods or "previous" in mods:
                kw.update(time_kind="relative", anchor="utterance_time", anchor_relation="before", value=head.norm)
            elif "next" in mods:
                kw.update(time_kind="relative", anchor="utterance_time", anchor_relation="after", value=head.norm)
        elif np.number is not None and head and head.lemma in L.TIME_UNITS:
            kw = dict(time_kind="duration", granularity=gran, offset={head.lemma + "s": np.number})
        elif "last" in mods or "previous" in mods:
            kw = dict(time_kind="relative", anchor="utterance_time", anchor_relation="before", granularity=gran, offset={(head.lemma + "s") if head else "units": -1})
        elif "next" in mods:
            kw = dict(time_kind="relative", anchor="utterance_time", anchor_relation="after", granularity=gran, offset={(head.lemma + "s") if head else "units": 1})
        elif "this" in mods or "that" in mods:
            kw = dict(time_kind="relative", anchor="utterance_time", anchor_relation="at", granularity=gran)
        else:
            kw = dict(time_kind="unspecified", granularity=gran, value=head.norm if head else None)
        return self.b.time(annotations=self._surface(np, "time"), **kw)

    def _time_from_adverb(self, tok: Token) -> str | None:
        n = tok.norm
        if n in L.DEICTIC_DAYS:
            off = L.DEICTIC_DAYS[n]
            kw: dict[str, Any] = dict(time_kind="relative", anchor="utterance_time", offset={"days": float(off)}, granularity="day",
                                      anchor_relation="before" if off < 0 else "after" if off > 0 else "at")
            if self.now is not None:
                kw["value"] = (self.now + timedelta(days=off)).date().isoformat()
            return self.b.time(annotations=self._surface(tok, "time"), **kw)
        if n in ("now", "currently", "today"):
            return self.b.time("relative", anchor="utterance_time", anchor_relation="at", granularity="day")
        if n in ("recently", "earlier", "before", "previously"):
            return self.b.time("relative", anchor="utterance_time", anchor_relation="before")
        if n in ("later", "soon", "tonight"):
            return self.b.time("relative", anchor="utterance_time", anchor_relation="after")
        if n in ("always", "usually", "often", "daily", "sometimes", "never", "weekly"):
            return self.b.time("recurrent", annotations={"frequency": n})
        return None

    # ------------------------------------------------------------------------------------------
    # Sentence / clause construction
    # ------------------------------------------------------------------------------------------
    def build(self) -> ACRDocument:
        for k, sent in enumerate(self.sentences):
            self.sent_idx = k
            self._sentence(sent)
        doc = self.b.build()
        doc.meta["text"] = self.text
        doc.meta["utterance_time"] = self.now.isoformat() if self.now else None
        return doc

    def _sentence(self, sent: ParsedSentence) -> None:
        feats = {"terminal": sent.terminal, "sentence": sent.index, "coverage": round(sent.coverage, 3),
                 "markers": [t.norm for t in sent.discourse_markers],
                 "emoji": [t.text for t in sent.tokens if t.kind == "emoji"]}
        from .social import detect_social
        social = detect_social(sent)
        if social is not None:
            act, extra = social
            iid = self.b.intention(act, agent=self.speaker(), addressee=self.addressee(), features={**feats, **extra}, root=True)
            self.b.doc.nodes[iid].annotations["social"] = True
            nwords = len([t for t in sent.tokens if t.kind in ("word", "clitic", "number")])
            from_marker = bool(extra.get("word")) and bool(sent.discourse_markers)
            if not sent.clauses or (not from_marker and nwords <= 6 and social_only(sent, act)):
                return
        if not sent.clauses:
            if sent.discourse_markers and not social:
                m = sent.discourse_markers[0].norm
                act = L.INTERJECTIONS.get(m, ("exclaim", 0.3, 0.3))[0]
                act = {"thank_or_farewell": "thank", "polite": "acknowledge"}.get(act, act)
                self.b.intention(act, agent=self.speaker(), addressee=self.addressee(), features=feats, root=True)
            return
        results = [self._clause(c, sent) for c in sent.clauses]
        self._link_clauses(sent.clauses, results)
        main_idx = next((i for i, c in enumerate(sent.clauses) if not c.connective_role or c.connective_role in ("coordinate", "juxtaposed", "contrast", "alternative", "result")), 0)
        # sentence-level speech act chosen by the mood of the first main clause
        main = sent.clauses[main_idx]
        content: list[str] = []
        for r in results:
            content += r["content"]
        if main.mood == "interrogative":
            focus = next((r["focus"] for r in results if r.get("focus")), None)
            act = "request_confirmation" if main.question_kind == "yes_no" else "request_information"
            qk = main.question_kind
            if any(r.get("ellipsis") for r in results):
                qk = "ellipsis"
            self.b.intention(act, agent=self.speaker(), addressee=self.addressee(), content=content,
                             features={**feats, "question_kind": qk, "focus": focus,
                                       "wh": (main.wh.wh if main.wh else main.wh_adv)}, root=True)
        elif main.mood == "imperative":
            self.b.intention("request_action", agent=self.speaker(), addressee=self.addressee(), content=content, features=feats, root=True)
        else:
            act = "assert"
            if not content:
                act = "fragment"
            self.b.intention(act, agent=self.speaker(), addressee=self.addressee(), content=content, features=feats, root=True)

    # ---- linking clauses ------------------------------------------------------------------------
    def _link_clauses(self, clauses: list[Clause], results: list[dict]) -> None:
        for k, c in enumerate(clauses):
            role = c.connective_role
            if not role or role in ("coordinate", "juxtaposed"):
                continue
            me = results[k]["main"]
            if me is None:
                continue
            partner = None
            for j in (range(k - 1, -1, -1) if k > 0 else range(1, len(clauses))):
                if j != k and results[j]["main"] is not None:
                    partner = results[j]["main"]
                    break
            if partner is None:
                continue
            if role in ("cause", "cause_or_time"):
                self.b.link("cause", me, partner, root=True)
            elif role == "condition":
                results[k]["content"] = [x for x in results[k]["content"] if x != me]
                self.b.condition(me, partner, root=True)
                self.b.doc.nodes[me].modality = "hypothetical" if hasattr(self.b.doc.nodes[me], "modality") else None
            elif role == "condition_negated":
                results[k]["content"] = [x for x in results[k]["content"] if x != me]
                neg = self.b.logical("not", [me])
                self.b.condition(neg, partner, root=True)
            elif role == "contrast":
                self.b.link("contrast", me, partner, root=True)
            elif role in ("temporal_before", "temporal_after", "temporal_simultaneous", "temporal_until"):
                lt = {"temporal_before": "after", "temporal_after": "before", "temporal_simultaneous": "during", "temporal_until": "before"}[role]
                self.b.link(lt, me, partner, root=True)
            elif role == "result":
                self.b.link("cause", partner, me, root=True)
            elif role == "complement":
                prev = self.b.doc.nodes.get(partner)
                if prev is not None and hasattr(prev, "roles"):
                    prev.roles.setdefault("theme", me)
            elif role == "alternative":
                self.b.link("alternative", partner, me, root=True)

    # ---- clause ---------------------------------------------------------------------------------
    def _clause(self, c: Clause, sent: ParsedSentence) -> dict:
        out: dict[str, Any] = {"content": [], "main": None, "focus": None}
        vg = c.vg
        # interrogative structures with a wh-adverb carry their own variable
        if c.mood == "interrogative":
            return self._question(c, out)
        if vg is None:
            return self._fragment(c, out)
        neg = vg.neg or any(a.norm in ("never",) for a in c.advs) or (c.subject is not None and c.subject.det is not None and c.subject.det.norm == "no") \
            or (c.subject is not None and c.subject.head is not None and c.subject.head.norm in ("nobody", "nothing"))
        if c.subject is not None and c.subject.kind == "pron" and c.subject.head is not None and c.subject.head.norm in ("nobody", "nothing"):
            neg = True
        node = self._predicate(c, neg)
        if node:
            out["content"].append(node)
            out["main"] = node
        return out

    def _fragment(self, c: Clause, out: dict) -> dict:
        nodes = []
        if c.subject is not None:
            n = self.np_node(c.subject, "fragment")
            if n:
                nodes.append(n)
        for np in c.objects:
            n = self.np_node(np, "fragment")
            if n:
                nodes.append(n)
        out["content"] = nodes
        out["main"] = nodes[0] if nodes else None
        return out

    # ---- predicates -----------------------------------------------------------------------------
    def _predicate(self, c: Clause, neg: bool, *, query: bool = False, subject_override: str | None = None,
                   variables: dict | None = None) -> str | None:
        vg = c.vg
        assert vg is not None
        subj_np = c.subject
        subj = subject_override or (self.np_node(subj_np, "subject", generic_ok=True) if subj_np is not None else None)
        if subj is None and c.inherited_subject:
            subj = None
        comp = c.complement
        copular = vg.copula or (vg.main is not None and L.VERBS.get(vg.main.lemma, ("", ""))[1] == "copula_like")
        if copular and comp is not None:
            return self._copular(c, subj, comp, neg, query)
        if copular and comp is None and c.pps:
            return self._copular_pp(c, subj, neg)
        if vg.main is None:
            return None
        return self._event(c, subj, neg, query)

    def _polarity(self, neg: bool) -> str:
        return "negative" if neg else "positive"

    def _time_slot(self, c: Clause) -> str | None:
        for tok in c.advs:
            t = self._time_from_adverb(tok)
            if t:
                return t
        for np in c.time_nps:
            return self.np_node(np, "time")
        return None

    # ---- events ---------------------------------------------------------------------------------
    def _event(self, c: Clause, subj: str | None, neg: bool, query: bool) -> str:
        vg = c.vg
        assert vg is not None and vg.main is not None
        lemma = vg.main.lemma
        action, frame_kind = L.VERBS.get(lemma, (f"act.{lemma}", "tr"))
        info = concepts.get(action)
        frame = info.frame if info else ("agent", "theme")
        roles: dict[str, str] = {}
        subj_role = frame[0] if frame else "agent"
        passive = vg.voice == "passive"
        objects = [self.np_node(o, "object") for o in c.objects]
        objects = [o for o in objects if o]
        slots: dict[str, str] = {}
        purpose = location = None
        cond_extra: list[str] = []
        if passive:
            # "The book was given to Michael by Sarah."
            if frame_kind == "ditr" and objects:
                if subj:
                    roles["recipient"] = subj
                roles["theme"] = objects[0]
            elif subj:
                roles[self._object_role(frame)] = subj
        else:
            if subj:
                roles[subj_role] = subj
            if frame_kind == "ditr" and len(objects) >= 2:
                roles["recipient"], roles["theme"] = objects[0], objects[1]
            elif objects:
                roles[self._object_role(frame)] = objects[0]
                if len(objects) > 1:
                    roles["attribute"] = objects[1]
        # elided numeric objects ("gives 2 to Anna") inherit the head noun of the previous event's theme
        for rname, rid in list(roles.items()):
            node = self.b.doc.nodes.get(rid)
            if node is not None and getattr(node, "ref_type", None) == "ellipsis":
                prev = self._last_event and self.b.doc.nodes.get(self._last_event)
                if prev is not None and hasattr(prev, "roles") and "theme" in prev.roles:
                    node.annotations["elided_head_of"] = prev.roles["theme"]
        for pp in c.pps:
            if pp.np is None:
                continue
            prep = pp.prep.norm
            node = self.np_node(pp.np, f"pp:{prep}")
            if node is None:
                continue
            if prep == "by" and passive:
                roles["agent"] = node
                continue
            if prep == "to" and "recipient" in frame and "recipient" not in roles:
                roles["recipient"] = node
                continue
            if prep == "for":
                n = self.b.doc.nodes[node]
                animate = getattr(n, "features", {}).get("animacy") in ("animate", "unknown") or getattr(n, "entity_type", "") == "class.person"
                if animate and action in ("act.give", "act.buy", "act.make", "act.cook", "act.build", "act.bring", "act.send", "act.help", "act.write"):
                    roles["beneficiary"] = node
                else:
                    purpose = node
                continue
            if prep in ("in", "at", "on", "inside", "near", "behind", "under", "over", "around", "between", "across"):
                n = self.b.doc.nodes[node]
                if getattr(n, "kind", "") != "time" and getattr(n, "entity_type", "class.entity") != "class.abstract" or True:
                    location = location or node
                    continue
            role = PREP_ROLE.get(prep, "attribute")
            if role in ("goal", "source", "topic", "comitative", "instrument", "path", "manner", "attribute", "measure"):
                roles.setdefault(role, node)
            elif role == "time_ref":
                roles.setdefault("time_ref", node)
        time = self._time_slot(c)
        modality = {"can": "possible", "could": "possible", "may": "possible", "might": "possible", "must": "obligatory",
                    "should": "obligatory", "ought": "obligatory", "would": "hypothetical"}.get(vg.modal or "", "actual")
        if c.infinitive is not None:
            inner = self._infinitive_event(c, subj)
            if inner:
                roles["theme"] = inner
        tense = vg.tense
        eid = self.b.event(action, roles, root=False, time=time, location=location, purpose=purpose,
                           tense=tense, aspect=vg.aspect, polarity=self._polarity(neg), modality=modality,
                           annotations={"lemma": lemma, "voice": vg.voice, **self._surface(vg.main, "verb"),
                                        **({"unknown_verb": True} if lemma not in L.VERBS else {})})
        if modality == "obligatory" and False:
            pass
        self._last_event = eid
        return eid

    @staticmethod
    def _object_role(frame: tuple[str, ...]) -> str:
        for r in ("theme", "stimulus"):
            if r in frame:
                return r
        return frame[1] if len(frame) > 1 else "theme"

    def _infinitive_event(self, c: Clause, subj: str | None) -> str | None:
        inf = c.infinitive
        if inf is None or inf.vg is None or inf.vg.main is None:
            return None
        lemma = inf.vg.main.lemma
        action, _ = L.VERBS.get(lemma, (f"act.{lemma}", "tr"))
        info = concepts.get(action)
        frame = info.frame if info else ("agent", "theme")
        roles: dict[str, str] = {}
        if subj:
            roles[frame[0]] = subj
        objs = [self.np_node(o, "object") for o in inf.objects]
        objs = [o for o in objs if o]
        if objs:
            roles[self._object_role(frame)] = objs[0]
        for pp in inf.pps:
            if pp.np is None:
                continue
            node = self.np_node(pp.np, "pp")
            if node:
                role = PREP_ROLE.get(pp.prep.norm, "attribute")
                roles.setdefault("location" if role == "location" else role, node)
        return self.b.event(action, roles, tense="present", modality="desired", annotations={"lemma": lemma, "infinitive": True})

    # ---- copular predications -------------------------------------------------------------------
    def _copular_pp(self, c: Clause, subj: str | None, neg: bool) -> str | None:
        pp = c.pps[0]
        if pp.np is None or subj is None:
            return None
        node = self.np_node(pp.np, "pp")
        pred = {"in": "rel.located_in", "at": "rel.located_in", "on": "rel.located_in", "from": "rel.origin", "near": "rel.near",
                "of": "rel.part_of"}.get(pp.prep.norm)
        if pred is None or node is None:
            return None
        return self.b.proposition(pred, {"figure": subj, "ground": node}, polarity=self._polarity(neg))

    def _copular(self, c: Clause, subj: str | None, comp: Any, neg: bool, query: bool) -> str | None:
        vg = c.vg
        assert vg is not None
        subj_np = c.subject
        time = self._time_slot(c)
        extra = {"time": time} if time else {}
        # ------------------------------------------------------------------------------------------
        if isinstance(comp, AdjP):
            return self._adjp_proposition(subj, comp, neg, vg, extra, subj_np)
        if isinstance(comp, PP):
            return self._copular_pp(Clause(tokens=[], vg=vg, pps=[comp]), subj, neg)
        if isinstance(comp, NP):
            return self._np_complement(c, subj, subj_np, comp, neg, extra)
        return None

    def _members(self, node_id: str | None) -> list[str]:
        if node_id is None:
            return []
        node = self.b.doc.nodes[node_id]
        if node.KIND == "logical" and node.op in ("and", "or"):  # type: ignore[attr-defined]
            return [m for o in node.operands for m in self._members(o)]  # type: ignore[attr-defined]
        return [node_id]

    def _adjp_proposition(self, subj: str | None, a: AdjP, neg: bool, vg: VG, extra: dict, subj_np: NP | None) -> str | None:
        if subj is None:
            return None
        info = L.GRADABLE.get(a.base)
        dim, pole = (info[0], info[1]) if info else (None, 1)
        if a.periphrastic in ("less", "least"):
            pole = -pole
        pol = self._polarity(neg)
        std = self.np_node(a.standard, "standard") if a.standard is not None else None
        subj_members = self._members(subj)
        annotation = {"adjective": a.base, "degree": a.degree}
        if a.degree == "cmp" and dim and std is not None:
            made = []
            for s in subj_members:
                for t in self._members(std):
                    greater, lesser = (s, t) if pole > 0 else (t, s)
                    made.append(self.b.proposition("rel.exceeds", {"greater": greater, "lesser": lesser, "dimension": self.b.concept(dim)},
                                                   polarity=pol, annotations=annotation, **extra))
            return made[0] if len(made) == 1 else self.b.logical("and", made)
        if a.equative and dim and std is not None:
            made = []
            for s in subj_members:
                for t in self._members(std):
                    if neg:   # "X is not as old as Y" -> Y exceeds X on the dimension
                        greater, lesser = (t, s) if pole > 0 else (s, t)
                        made.append(self.b.proposition("rel.exceeds", {"greater": greater, "lesser": lesser, "dimension": self.b.concept(dim)},
                                                       annotations={**annotation, "from": "negated_equative"}, **extra))
                    else:
                        made.append(self.b.proposition("rel.equal_on", {"first": s, "second": t, "dimension": self.b.concept(dim)},
                                                       annotations=annotation, **extra))
            return made[0] if len(made) == 1 else self.b.logical("and", made)
        if a.degree == "sup" and dim:
            domain = std
            return self.b.proposition("rel.extreme", {"subject": subj, **({"domain": domain} if domain else {}),
                                                      "dimension": self.b.concept(dim)}, polarity=pol,
                                      annotations={**annotation, "pole": "high" if pole > 0 else "low"}, **extra)
        if a.measure is not None and a.base in L.MEASURE_ADJECTIVES:
            md = L.MEASURE_ADJECTIVES[a.base]
            unit = a.measure.measure_unit or (a.measure.head.lemma if a.measure.head else None)
            q = self.b.quantity(a.measure.number or 0, unit, md)
            prop = concepts.get(md).meta["property"] if concepts.get(md) else f"prop.{a.base}"
            return self.b.proposition("rel.has_property", {"subject": subj, "property": self.b.concept(prop), "value": q},
                                      polarity=pol, annotations=annotation, **extra)
        prop = self.b.concept(f"prop.{a.base}", a.base, annotations={"dimension": dim, "pole": pole} if dim else {})
        node = self.b.proposition("rel.has_property", {"subject": subj, "property": prop}, polarity=pol,
                                  annotations={**annotation, "relative": bool(dim)}, **extra)
        if subj_np is not None and subj_np.quant in ("all", "most", "some", "no", "few"):
            self.b.doc.nodes[node].quantifier = subj_np.quant  # type: ignore[attr-defined]
        elif subj_np is not None and subj_np.kind == "common" and subj_np.det is None and subj_np.plural:
            self.b.doc.nodes[node].quantifier = "all"          # generic plural: "Dogs are loyal."  (defeasible)
            self.b.doc.nodes[node].annotations["generic"] = True
        return node

    def _np_complement(self, c: Clause, subj: str | None, subj_np: NP | None, comp: NP, neg: bool, extra: dict) -> str | None:
        pol = self._polarity(neg)
        # attribute-of on the subject side: "My name is Alex", "The capital of France is Paris"
        if subj_np is not None and subj_np.head is not None and subj_np.kind == "common" and subj_np.head.lemma in L.RELATIONAL_NOUNS \
                and (subj_np.possessor is not None or subj_np.of_np is not None):
            owner = self.np_node(subj_np.possessor, "owner") if subj_np.possessor is not None else self.np_node(subj_np.of_np, "owner", generic_ok=False)
            value = self._value_node(comp)
            if owner and value:
                return self.b.proposition(f"attr.{subj_np.head.lemma}", {"owner": owner, "value": value}, polarity=pol, **extra)
        # attribute-of on the complement side: "Paris is the capital of France"
        if comp.head is not None and comp.kind == "common" and comp.head.lemma in L.RELATIONAL_NOUNS and comp.of_np is not None and subj is not None:
            owner = self.np_node(comp.of_np, "owner", generic_ok=False)
            if owner:
                return self.b.proposition(f"attr.{comp.head.lemma}", {"owner": owner, "value": subj}, polarity=pol, **extra)
        if comp.head is not None and comp.kind == "common" and comp.head.lemma in L.RELATIONAL_NOUNS and comp.possessor is not None and subj is not None:
            owner = self.np_node(comp.possessor, "owner")
            if owner:
                return self.b.proposition(f"attr.{comp.head.lemma}", {"owner": owner, "value": subj}, polarity=pol, **extra)
        # superlative nominal: "John is the oldest"
        if comp.kind == "nominal_adj" and comp.superlative is not None and subj is not None:
            sup = comp.superlative
            info = L.GRADABLE.get(sup.lemma)
            if info:
                dim, pole = info[0], info[1]
                if sup.feats.get("degree") == "sup":
                    return self.b.proposition("rel.extreme", {"subject": subj, "dimension": self.b.concept(dim)}, polarity=pol,
                                              annotations={"adjective": sup.lemma, "pole": "high" if pole > 0 else "low"}, **extra)
        if subj is None:
            return None
        # class membership / identity
        if comp.kind in ("name",) or (comp.kind == "common" and comp.head is not None and comp.head.pos == "PROPN"):
            value = self.np_node(comp, "complement")
            return self.b.proposition("rel.identical", {"first": subj, "second": value}, polarity=pol, **extra) if value else None
        if comp.kind == "pron":
            value = self.np_node(comp, "complement")
            return self.b.proposition("rel.identical", {"first": subj, "second": value}, polarity=pol, **extra) if value else None
        # generic statements: "A dog is a mammal." -> kinds, universally quantified (present tense, no time)
        generic = (subj_np is not None and subj_np.kind == "common" and subj_np.head is not None and subj_np.det is not None
                   and subj_np.det.norm in ("a", "an") and comp.kind == "common" and comp.det is not None and comp.det.norm in ("a", "an")
                   and c.vg is not None and c.vg.tense == "present" and not extra and not subj_np.adjs)
        if generic:
            subj = self.b.concept(f"kind.{subj_np.head.lemma}", subj_np.head.lemma, annotations={"plural": False, "quantifier": "generic"})
        if comp.kind == "common" and comp.head is not None:
            kind_id = self.b.concept(f"kind.{comp.head.lemma}", comp.head.lemma,
                                     annotations={"plural": comp.plural, "adjectives": [a.lemma for a in comp.adjs]})
            node = self.b.proposition("rel.is_a", {"subject": subj, "object": kind_id}, polarity=pol, **extra)
            if generic:
                self.b.doc.nodes[node].quantifier = "all"
                self.b.doc.nodes[node].annotations["generic"] = True
            elif subj_np is not None:
                if subj_np.quant in ("all", "most", "some", "no", "few"):
                    self.b.doc.nodes[node].quantifier = subj_np.quant  # type: ignore[attr-defined]
                elif subj_np.kind == "common" and subj_np.det is None and subj_np.plural:
                    self.b.doc.nodes[node].quantifier = "all"
                    self.b.doc.nodes[node].annotations["generic"] = True
            return node
        return None

    def _value_node(self, comp: NP) -> str | None:
        if comp.kind in ("name", "common", "pron", "group"):
            return self.np_node(comp, "value", generic_ok=False)
        if comp.number is not None:
            return self.b.literal(comp.number)
        return None

    # ------------------------------------------------------------------------------------------
    # Questions
    # ------------------------------------------------------------------------------------------
    def _question(self, c: Clause, out: dict) -> dict:
        qk = c.question_kind
        vg = c.vg
        neg = bool(vg and vg.neg)
        if qk == "wh_identify":
            return self._wh_identify(c, out)
        if qk == "wh_degree":
            subj = self.np_node(c.subject, "subject") if c.subject else None
            adj = c.wh_adj
            if subj and adj:
                info = L.GRADABLE.get(adj.lemma)
                dim = info[0] if info else None
                prop_id = concepts.get(dim).meta["property"] if dim and concepts.get(dim) else f"prop.{adj.lemma}"
                var = self.b.variable("how_" + adj.lemma, quantity=True, dimension=dim)
                node = self.b.proposition("rel.has_property", {"subject": subj, "property": self.b.concept(prop_id), "value": var}, modality="queried")
                out.update(content=[node], main=node, focus=var)
            return out
        if qk == "wh_adjunct":
            if vg is not None and vg.copula and c.wh_adv == "how":
                # "How are you?" / "How is John?"
                subj = self.np_node(c.subject, "subject") if c.subject else None
                var = self.b.variable("how", constraints_="state")
                node = self.b.proposition("rel.has_state", {"subject": subj, "state": var}, modality="queried") if subj else None
                out.update(content=[node] if node else [], main=node, focus=var)
                return out
            var = self.b.variable(c.wh_adv or "wh", adjunct=c.wh_adv)
            subj = self.np_node(c.subject, "subject") if c.subject else None
            if vg is not None and vg.main is not None:
                ev = self._event(c, subj, neg, True)
                evn = self.b.doc.nodes[ev]
                slot = {"where": "location", "when": "time", "why": "cause", "how": "manner"}.get(c.wh_adv or "", "attribute")
                if slot == "location":
                    evn.location = var
                elif slot == "time":
                    evn.time = var
                else:
                    evn.roles[slot] = var
                evn.modality = "queried" if False else evn.modality
                evn.annotations["queried"] = True
                out.update(content=[ev], main=ev, focus=var)
            elif vg is not None and vg.copula and subj:
                node = self.b.proposition("rel.located_in" if c.wh_adv == "where" else "rel.has_property",
                                          {"figure": subj, "ground": var} if c.wh_adv == "where" else {"subject": subj, "property": var}, modality="queried")
                out.update(content=[node], main=node, focus=var)
            return out
        subj_np = c.subject
        # who/what/which as subject of an event: "Who gave Michael a book?"
        if qk == "wh_subject" and vg is not None and vg.main is not None:
            var = self._wh_variable(c.wh) if c.wh else self.b.variable("who")
            ev = self._event(c, var, neg, True)
            self.b.doc.nodes[ev].annotations["queried"] = True
            out.update(content=[ev], main=ev, focus=var)
            return out
        if qk == "wh_object" and vg is not None:
            var = self._wh_variable(c.wh) if c.wh else self.b.variable("what")
            subj = self.np_node(subj_np, "subject") if subj_np else None
            if vg.main is None:
                return out
            frame_action = L.VERBS.get(vg.main.lemma, (f"act.{vg.main.lemma}", "tr"))[0]
            info = concepts.get(frame_action)
            frame = info.frame if info else ("agent", "theme")
            ev = self._event(c, subj, neg, True)
            evn = self.b.doc.nodes[ev]
            # which role does the wh-phrase fill?  the first frame role not already filled (object role preferred)
            target = None
            role_pref = [self._object_role(frame)] + [r for r in frame[1:] if r not in (self._object_role(frame),)]
            ditr = L.VERBS.get(vg.main.lemma, ("", ""))[1] == "ditr"
            if ditr and not c.objects:
                role_pref = ["theme", "recipient"]
            for r in role_pref:
                if r not in evn.roles:
                    target = r
                    break
            evn.roles[target or "theme"] = var
            evn.annotations["queried"] = True
            out.update(content=[ev], main=ev, focus=var)
            return out
        # elliptical follow-ups: "What about David?" / "And Peter?"  (completed by the Context Engine)
        if qk == "ellipsis" or (qk == "yes_no" and vg is None and subj_np is not None):
            node = self.np_node(subj_np, "subject") if subj_np else None
            if node:
                self.b.doc.nodes[node].annotations["ellipsis_fragment"] = True
                out.update(content=[node], main=None, focus=None, ellipsis=node)
            return out
        # yes/no questions
        if qk == "yes_no" or (c.mood == "interrogative" and qk is None):
            subj = self.np_node(subj_np, "subject") if subj_np else None
            node = None
            if vg is not None:
                if vg.copula and c.complement is not None:
                    node = self._copular(c, subj, c.complement, neg, True)
                elif vg.copula and c.pps:
                    node = self._copular_pp(c, subj, neg)
                elif vg.main is not None:
                    node = self._event(c, subj, neg, True)
            if node is not None:
                self.b.doc.nodes[node].annotations["queried"] = True
                out.update(content=[node], main=node)
            return out
        return out

    def _wh_identify(self, c: Clause, out: dict) -> dict:
        comp = c.complement
        wh = c.wh
        if comp is None or wh is None:
            return out
        var = self._wh_variable(wh)
        if isinstance(comp, AdjP):
            # "What is older than Peter?" / "Who is taller than Anna?"
            node = self._adjp_proposition(var, comp, False, c.vg, {}, None)  # type: ignore[arg-type]
            if node:
                self.b.doc.nodes[node].annotations["queried"] = True
                out.update(content=[node], main=node, focus=var)
            return out
        if not isinstance(comp, NP):
            return out
        # "Who is the youngest?"
        if comp.kind == "nominal_adj" and comp.superlative is not None:
            info = L.GRADABLE.get(comp.superlative.lemma)
            if info:
                node = self.b.proposition("rel.extreme", {"subject": var, "dimension": self.b.concept(info[0])},
                                          annotations={"adjective": comp.superlative.lemma, "pole": "high" if info[1] > 0 else "low",
                                                       "queried": True})
                out.update(content=[node], main=node, focus=var)
                return out
        # "Who is the tallest person?" -> same as the nominal superlative; a generic person noun adds no restriction
        if comp.kind == "common" and comp.head is not None and comp.head.lemma in {"person", "one", "man", "woman", "boy", "girl", "guy", "kid", "child"}:
            sup = comp.superlative or next((a for a in comp.adjs if a.feats.get("degree") == "sup"), None)
            info = L.GRADABLE.get(sup.lemma) if sup is not None else None
            if info:
                node = self.b.proposition("rel.extreme", {"subject": var, "dimension": self.b.concept(info[0])},
                                          annotations={"adjective": sup.lemma, "pole": "high" if info[1] > 0 else "low", "queried": True})
                out.update(content=[node], main=node, focus=var)
                return out
        # choice question: "Who is older, John or Peter?" -> the extreme (of the two candidates) on the adjective's dimension
        lead = comp.members[0] if comp.kind == "group" and comp.members else comp
        if lead.adjs and lead.head is not None:
            adj = lead.adjs[-1]
            info = L.GRADABLE.get(adj.lemma)
            if info and adj.feats.get("degree") in ("cmp", "sup"):
                cands = self.np_node(comp, "complement", generic_ok=False)
                if cands:
                    node = self.b.proposition("rel.extreme", {"subject": var, "dimension": self.b.concept(info[0]), "candidates": cands},
                                              annotations={"adjective": adj.lemma, "pole": "high" if info[1] > 0 else "low", "queried": True,
                                                           "choice": True})
                    out.update(content=[node], main=node, focus=var)
                    return out
        # "Who is the tallest of the three?" falls through to nominal adjective with domain via of_np
        # "What is the capital of France?" / "What is my name?"
        if comp.head is not None and comp.head.lemma in L.RELATIONAL_NOUNS and comp.kind == "common" and (comp.of_np is not None or comp.possessor is not None):
            owner = self.np_node(comp.of_np, "owner", generic_ok=False) if comp.of_np is not None else self.np_node(comp.possessor, "owner")
            if owner:
                node = self.b.proposition(f"attr.{comp.head.lemma}", {"owner": owner, "value": var}, annotations={"queried": True})
                out.update(content=[node], main=node, focus=var)
                return out
        # "Who is Sarah?" / "What is a dog?" -> definition/identity question
        target = self.np_node(comp, "complement", generic_ok=True)
        if target:
            node = self.b.proposition("rel.is_a" if comp.kind == "common" else "rel.identical",
                                      {"subject": target, "object": var} if comp.kind == "common" else {"first": target, "second": var},
                                      annotations={"queried": True, "definition": True})
            out.update(content=[node], main=node, focus=var)
        return out


def social_only(sent: ParsedSentence, act: str) -> bool:
    """True when the sentence carries nothing beyond its social act (so no content clause is built)."""
    if act in ("greet", "farewell", "thank", "apologize", "acknowledge", "affirm", "deny", "exclaim", "social_inquiry"):
        return True
    return False
