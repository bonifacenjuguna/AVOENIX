"""Rule-based part-of-speech tagging: lexicon candidates + ordered contextual rules.

The design follows the classic traditional pipeline: (1) a lexicon and morphology produce a
*set* of possible tags per token; (2) contextual disambiguation rules (Brill-style, applied in
a fixed order) choose among them. Unknown words are handled by capitalisation, suffix and
context rules instead of being rejected. No statistical model, no pretrained resource.
"""

from __future__ import annotations

from .lexicon import (
    ADVERBS_COMMON, AUX_BE, AUX_DO, AUX_HAVE, CCONJ, COMMON_NOUNS, DETERMINERS, FEMALE_NAMES, GRADABLE, INTERJECTIONS,
    IRREGULAR_VERBS, MALE_NAMES, MODALS, NUMBER_WORDS, ORDINALS, POSSESSIVE_DETS, PREPOSITIONS, PRONOUNS, SCALE_WORDS,
    SCONJ, VERBS, WH_WORDS, EXTRA_VERBS, PERSON_NOUNS, ANIMAL_NOUNS, PLACE_NOUNS, ABSTRACT_NOUNS, RELATIONAL_NOUNS,
    DEICTIC_DAYS, WEEKDAYS, MONTHS, TIME_UNITS, UNITS, ARITH_WORDS, COMPARATIVE_FORMS,
)
from .lexicon_open import ADJECTIVES, NOUN_VERB
from .morphology import degree_analysis, guess_degree, guess_verb, singularize, verb_analysis
from .tokenizer import Token

KNOWN_NOUNS = COMMON_NOUNS | PERSON_NOUNS | ANIMAL_NOUNS | PLACE_NOUNS | ABSTRACT_NOUNS | RELATIONAL_NOUNS | NOUN_VERB
NAMES = MALE_NAMES | FEMALE_NAMES
SUBJECT_TAGS = {"PRON", "NOUN", "PROPN"}
_NP_TAGS = {"DET", "ADJ", "NUM", "NOUN", "PROPN", "PRON"}


def _candidates(tok: Token, first: bool) -> list[str]:
    n = tok.norm
    if tok.kind == "punct":
        return ["PUNCT"]
    if tok.kind == "emoji":
        return ["EMOJI"]
    if tok.kind in ("url", "email"):
        return ["X"]
    if tok.kind in ("number", "time"):
        return ["NUM"]
    if tok.kind == "clitic":
        return {"'s": ["POSS", "AUX"], "'re": ["AUX"], "'m": ["AUX"], "'ve": ["AUX"], "'ll": ["AUX"], "'d": ["AUX"]}.get(n, ["X"])
    cands: list[str] = []
    cap = tok.text[:1].isupper()

    def add(pos: str) -> None:
        if pos not in cands:
            cands.append(pos)

    if n in ("not",):
        return ["PART"]
    if n == "to":
        return ["PART", "ADP"]
    if n in POSSESSIVE_DETS and n != "her":
        return ["DET"]
    if n == "her":
        return ["DET", "PRON"]
    if n in MODALS:
        return ["AUX"]
    if n in AUX_BE:
        return ["AUX"]
    if n in AUX_HAVE or n in AUX_DO:
        return ["AUX", "VERB"]
    if n in WH_WORDS and n not in ("what", "which", "who", "whom", "whose"):
        return ["ADV"]
    if n in ("what", "which", "whose"):
        return ["DET", "PRON"]
    if n in ("who", "whom"):
        return ["PRON"]
    if n == "that":
        return ["DET", "PRON", "SCONJ"]
    if n in ("this", "these", "those"):
        return ["DET", "PRON"]
    if n == "one":
        return ["NUM", "PRON"]
    if n == "no":
        return ["DET", "INTJ"]
    if n in ("so",):
        return ["ADV", "CCONJ", "SCONJ"]
    if n in ("like",):
        return ["VERB", "ADP"]
    if n in ("as",):
        return ["ADV", "ADP", "SCONJ"]
    if n in ("since", "before", "after", "until", "till"):
        return ["ADP", "SCONJ"]
    if n in ("when", "while", "if", "because", "although", "though", "unless", "whereas", "once", "whether"):
        return ["SCONJ"]
    if n in CCONJ:
        return ["CCONJ"]
    if n in PRONOUNS and n not in ("one", "ones"):
        return ["PRON"]
    if n in DETERMINERS and n not in ("what", "which"):
        return ["DET"]
    if n in INTERJECTIONS and n not in ("no", "please", "well", "like", "thank", "welcome", "great", "cool", "sure", "right", "okay"):
        return ["INTJ"]
    if n in ("please",):
        return ["INTJ", "ADV"]
    if n in ("thank",):
        return ["VERB", "INTJ"]
    if n in PREPOSITIONS and n not in ("up", "down", "off", "near", "over", "like", "close"):
        add("ADP")
    # numbers and ordinals
    if n in NUMBER_WORDS or n in SCALE_WORDS:
        add("NUM")
    if n in ORDINALS and n not in ("last", "next", "previous", "final"):
        add("ADJ")
    if n in ARITH_WORDS and n not in ("over", "added"):
        add("CCONJ")
    # morphology-driven candidates
    degree = degree_analysis(n)
    if n in GRADABLE or degree:
        add("ADJ")
    if n in ADJECTIVES or n in ORDINALS:
        add("ADJ")
    if n in NOUN_VERB:
        add("NOUN"); add("VERB")
    va = verb_analysis(n)
    singular, plural = singularize(n)
    noun_known = n in KNOWN_NOUNS or singular in KNOWN_NOUNS or n in DEICTIC_DAYS or n in WEEKDAYS or n in MONTHS or n in TIME_UNITS \
        or n in UNITS or singular in TIME_UNITS
    if va:
        add("VERB")
    elif n.endswith("s") and singular in NOUN_VERB:
        add("VERB")                     # "it rains", "she plans": noun-verb homographs inflect as verbs too
    if noun_known:
        add("NOUN")
    if n in ADVERBS_COMMON:
        add("ADV")
    if n in ("up", "down", "off", "near", "over"):
        add("ADP"); add("ADV")
    if n.endswith("ly") and len(n) > 4 and not cands:
        add("ADV")
    # names
    if n in NAMES and (cap or not cands):
        cands.insert(0, "PROPN") if cap and not first else cands.append("PROPN")
    if not cands:
        if cap and (not first or n not in KNOWN_NOUNS):
            add("PROPN")
        g = guess_verb(n)
        if g:
            add("VERB")
        if guess_degree(n):
            add("ADJ")
        if n.endswith(("ful", "less", "ous", "ive", "able", "ible", "ical", "ish", "ic", "ant", "ent")):
            add("ADJ")
        add("NOUN")
    # sentence-initial capitalised known noun that is also a name stays ambiguous; plain capital -> proper noun
    if cap and not first and "PROPN" not in cands and not (va and "VERB" in cands[:1]) and n not in ADVERBS_COMMON and n not in ADJECTIVES \
            and n not in DEICTIC_DAYS and n not in KNOWN_NOUNS:
        cands.insert(0, "PROPN")
    if cap and n in WEEKDAYS + MONTHS:
        cands = ["PROPN", "NOUN"] if n != "may" else ["PROPN", "AUX"]
    return cands


def _nxt(tokens: list[Token], i: int, skip: set[str] = frozenset({"ADV", "PART"})) -> Token | None:
    j = i + 1
    while j < len(tokens):
        t = tokens[j]
        if t.pos in skip and t.norm not in ("to",):
            j += 1
            continue
        return t
    return None


def _can(tok: Token | None, pos: str) -> bool:
    return bool(tok) and pos in tok.cands


def _clause_follows(tokens: list[Token], i: int) -> bool:
    """After tokens[i], does a noun phrase followed by a verb/aux begin? (marks a subordinating use)"""
    j = i + 1
    seen_np = False
    while j < len(tokens) and tokens[j].pos in ("DET", "ADJ", "NUM", "NOUN", "PROPN", "PRON") or (j < len(tokens) and tokens[j].kind == "clitic" and tokens[j].pos == "POSS"):
        seen_np = True
        j += 1
    return seen_np and j < len(tokens) and tokens[j].pos in ("VERB", "AUX")


def tag_sentence(tokens: list[Token]) -> None:
    """Assign ``pos``, ``lemma`` and ``feats`` to every token in a sentence (in place)."""
    for k, tok in enumerate(tokens):
        tok.cands = _candidates(tok, first=(k == 0))
        tok.pos = tok.cands[0]
    # two passes so that decisions can see right-hand context that was decided in pass one
    for _ in range(2):
        for i, tok in enumerate(tokens):
            if len(tok.cands) > 1 or tok.pos in ("AUX", "POSS"):
                tok.pos = _decide(tokens, i)
    for i, tok in enumerate(tokens):
        _finalise(tok, tokens, i)


def _prev(tokens: list[Token], i: int, skip: set[str] = frozenset()) -> Token | None:
    j = i - 1
    while j >= 0 and tokens[j].pos in skip:
        j -= 1
    return tokens[j] if j >= 0 else None


def _decide(tokens: list[Token], i: int) -> str:
    tok = tokens[i]
    n = tok.norm
    c = tok.cands
    prev = tokens[i - 1] if i > 0 else None
    nxt = tokens[i + 1] if i + 1 < len(tokens) else None
    nxt2 = _nxt(tokens, i)
    prev_content = _prev(tokens, i, {"ADV"})

    # a capitalised word in the middle of a sentence that can be a name is a name ("Tom met Anna and Mark")
    if i > 0 and tok.text[:1].isupper() and "PROPN" in c and tok.kind == "word" and not tok.text.isupper() \
            and not (prev and prev.pos == "PUNCT" and prev.norm in (".", "!", "?")):
        return "PROPN"
    # ---- closed-class words with several readings ---------------------------------------------
    if n == "to":
        if nxt and (nxt.pos in ("DET", "PRON", "PROPN", "NUM") or (nxt.pos == "ADJ" and "VERB" not in nxt.cands)):
            return "ADP"
        if nxt and "VERB" in nxt.cands and nxt.pos != "DET":
            return "PART" if nxt.kind == "word" else "ADP"
        return "ADP"
    if tok.kind == "clitic":
        if n == "'s":
            if prev and prev.pos == "PRON":
                return "AUX"
            if nxt and nxt.kind == "word" and ("NOUN" in nxt.cands or "PROPN" in nxt.cands) and "VERB" not in nxt.cands[:1] \
                    and nxt.pos not in ("ADV",):
                return "POSS"
            if nxt and nxt.pos == "ADJ" and len(tokens) > i + 2 and tokens[i + 2].pos in ("NOUN", "PROPN"):
                return "POSS"
            return "AUX"
        return "AUX"
    if n == "her":
        if nxt and (("NOUN" in nxt.cands and "VERB" not in nxt.cands[:1]) or (nxt.pos == "ADJ" and len(tokens) > i + 2)) and nxt.pos not in ("DET", "PART"):
            return "DET"
        return "PRON"
    if n == "that":
        if nxt and nxt.norm in ("one", "ones"):
            return "DET"
        if prev and prev.pos in ("NOUN", "PROPN", "PRON") and nxt and nxt.pos in ("VERB", "AUX"):
            return "PRON"                      # relative pronoun: "the book that fell"
        if prev and prev.pos in ("NOUN", "PROPN") and nxt and nxt.pos in ("PRON", "DET", "PROPN", "NOUN", "ADJ") and _clause_follows(tokens, i):
            return "PRON"                      # "the book that Michael needed" (object relative)
        if nxt and nxt.pos in ("PRON", "DET", "PROPN") and nxt.norm not in ("is",) and _clause_follows(tokens, i):
            return "SCONJ"                     # complementizer: "said that she left"
        if nxt and nxt.pos in ("NOUN", "ADJ", "PROPN") and not (nxt.pos in ("VERB", "AUX")):
            return "DET"
        return "PRON"
    if n in ("this", "these", "those"):
        return "DET" if nxt and nxt.pos in ("NOUN", "ADJ", "PROPN", "NUM") else "PRON"
    if n in ("what", "which", "whose"):
        return "DET" if nxt and nxt.pos in ("NOUN", "ADJ", "NUM") and not (nxt.pos == "NOUN" and "VERB" in nxt.cands and tokens[i + 1:i + 3] and tokens[i + 2].pos in ("DET", "NOUN", "ADJ", "PROPN")) else "PRON"
    if n == "no":
        return "DET" if nxt and nxt.pos in ("NOUN", "ADJ", "NUM") else "INTJ"
    if n == "one":
        if prev and prev.pos in ("ADJ", "DET") and not (nxt and nxt.pos in ("NOUN", "PROPN")):
            return "PRON"
        return "NUM"
    if n == "so":
        if nxt and nxt.pos in ("ADJ", "ADV"):
            return "ADV"
        if nxt and nxt.pos in ("PRON", "DET", "PROPN", "NOUN") and (prev is None or prev.pos == "PUNCT"):
            return "CCONJ"
        return "CCONJ" if nxt and nxt.pos in ("PRON", "DET", "PROPN") else "ADV"
    if n == "as":
        if nxt and nxt.pos in ("ADJ", "ADV") and not (nxt.pos == "ADJ" and len(tokens) > i + 2 and tokens[i + 2].pos in ("NOUN", "PROPN")):
            return "ADV"
        return "SCONJ" if _clause_follows(tokens, i) else "ADP"
    if n in ("since", "before", "after", "until", "till"):
        return "SCONJ" if _clause_follows(tokens, i) else "ADP"
    if n == "like":
        if prev and prev.pos in ("PRON", "PROPN", "NOUN") and prev.norm not in ("something", "nothing") and not (prev.pos == "NOUN" and prev.norm.endswith("ing")):
            return "VERB"
        if prev and prev.pos in ("AUX", "PART"):
            return "VERB"
        if prev is None or prev.pos in ("PUNCT", "CCONJ"):
            return "VERB"
        return "ADP"
    if n == "please":
        return "INTJ" if (i == 0 or (prev and prev.pos == "PUNCT") or (nxt is None) or (nxt and nxt.pos == "PUNCT")) else "ADV"
    if n == "thank":
        return "INTJ" if nxt and nxt.norm == "you" else "VERB"

    # ---- auxiliaries -------------------------------------------------------------------------
    if n in AUX_HAVE or n in AUX_DO:
        if i == 0 or (prev and (prev.pos == "PUNCT" or prev.norm in WH_WORDS or prev.pos == "CCONJ")):
            # inverted question "do you...", "has she..." - but "has" may also be possession ("has a dog")
            if n in AUX_DO:
                return "AUX"
            if nxt and nxt.pos in ("PRON", "PROPN", "NOUN", "DET") and any(t.pos == "VERB" or (t.pos == "AUX" and False) for t in tokens[i + 2:i + 5]):
                return "AUX"
            return "AUX" if n in AUX_HAVE and any(t.pos == "VERB" and t.norm in participle_forms() for t in tokens[i + 1:i + 5]) else ("AUX" if n in AUX_DO else "VERB")
        look = nxt2
        if n in AUX_HAVE:
            if look and ("VERB" in look.cands) and (verb_form_of(look) in ("participle", "past")):
                return "AUX"
            return "VERB"
        # do-support: aux when a bare verb follows ("does not like", "did go") or after an
        # inverted subject ("does Tom have", "did the teacher say")
        if look and "VERB" in look.cands and look.pos != "DET":
            return "AUX"
        j = i + 1
        while j < len(tokens) and tokens[j].pos in ("DET", "ADJ", "NUM", "NOUN", "PROPN", "PRON", "POSS") and not (tokens[j].pos == "NOUN" and "VERB" in tokens[j].cands and j + 1 < len(tokens) and tokens[j + 1].pos == "PUNCT" and False):
            j += 1
        while j < len(tokens) and tokens[j].pos in ("ADV", "PART"):
            j += 1
        if j > i + 1 and j < len(tokens) and "VERB" in tokens[j].cands and any(t.norm in WH_WORDS or t.pos == "PUNCT" for t in tokens[:i]) or (j > i + 1 and j < len(tokens) and "VERB" in tokens[j].cands and i == 0):
            return "AUX"
        return "VERB"

    # ---- noun / verb / adjective ambiguity ---------------------------------------------------
    if "NOUN" in c and "VERB" in c:
        return _noun_or_verb(tokens, i, prev, nxt, tok)
    if "ADJ" in c and ("NOUN" in c or "VERB" in c or "ADV" in c):
        if nxt and nxt.norm in ("one", "ones") and prev and prev.pos in ("DET", "ADJ", "POSS"):
            return "ADJ"
        if prev and prev.pos in ("DET", "ADJ", "NUM", "POSS") and nxt and nxt.pos in ("NOUN", "PROPN", "ADJ"):
            return "ADJ"
        if prev and prev.pos == "AUX" and prev.norm in AUX_BE:
            return "ADJ"
        if prev and prev.pos in ("DET", "POSS") or (prev and prev.pos == "ADJ" and "NOUN" in c):
            return "NOUN" if "NOUN" in c else "ADJ"
        if "ADV" in c and prev and prev.pos in ("VERB", "AUX"):
            return "ADV" if not (nxt and nxt.pos in ("NOUN", "DET")) else c[0]
        if "VERB" in c and prev and prev.pos in ("PRON", "PROPN", "NOUN") and nxt and nxt.pos in ("DET", "NOUN", "PRON", "PROPN"):
            return "VERB"
        return c[0]
    if "ADP" in c and "ADV" in c:
        return "ADP" if nxt and nxt.pos in ("DET", "NOUN", "PROPN", "PRON", "NUM", "ADJ") else "ADV"
    if "PROPN" in c and ("NOUN" in c or "VERB" in c or "AUX" in c or "ADJ" in c):
        if i > 0 and tok.text[:1].isupper():
            return "PROPN"
        if i == 0 and nxt and nxt.pos in ("VERB", "AUX"):
            return "PROPN"
        return next(p for p in c if p != "PROPN")
    if "PROPN" in c and tok.pos not in c:
        return c[0]
    if "VERB" in c and "ADJ" in c:
        return "VERB"
    return tok.pos if tok.pos in c else c[0]


def _noun_or_verb(tokens: list[Token], i: int, prev: Token | None, nxt: Token | None, tok: Token) -> str:
    c = tok.cands
    n = tok.norm
    va = verb_analysis(n)
    form = va[1] if va else None
    if not va and n.endswith("s") and singularize(n)[0] in NOUN_VERB:
        form = "3sg"
    nxt_c = nxt.cands if nxt else []
    if form == "gerund" and prev and prev.pos in ("AUX", "ADP", "VERB", "PUNCT") and "NOUN" not in KNOWN_NOUNS:
        return "VERB"
    if form == "gerund" and prev and prev.pos == "AUX" and prev.norm in AUX_BE:
        return "VERB"
    if form in ("past", "participle") and "NOUN" not in c:
        return "VERB"
    if prev is None or prev.pos == "PUNCT":
        # sentence initial: imperative if followed by an argument, else noun subject
        if nxt and nxt.pos in ("DET", "PRON", "PROPN", "NUM", "ADV", "ADJ", "ADP", "PART") and not (nxt.pos == "ADV" and nxt.norm in ("is", "was")):
            return "VERB"
        if nxt and nxt.pos in ("NOUN",) and "VERB" in nxt_c and "NOUN" not in nxt_c[:1]:
            return "NOUN"
        if nxt and "NOUN" in nxt_c and "VERB" in nxt_c and singularize(n)[1]:
            return "NOUN"          # "Plans change": plural-looking first word is the subject
        if nxt and nxt.pos in ("NOUN",):
            return "VERB"
        return "NOUN" if nxt and nxt.pos in ("VERB", "AUX") else "VERB"
    if prev.pos in ("DET", "ADJ", "NUM", "POSS") or prev.pos == "NOUN" and prev.feats.get("compound_ok", False):
        return "NOUN"
    if prev.pos == "AUX" and prev.norm in (MODALS | set(AUX_DO)):
        return "VERB"
    if prev.pos == "PART" and prev.norm in ("to", "not"):
        return "VERB"
    if prev.pos == "PRON" and prev.feats.get("case") != "acc" and prev.norm not in ("me", "him", "them", "us", "it_"):
        return "VERB"
    if prev.pos in ("NOUN", "PROPN"):
        # "<subject noun> <verb> ..." vs compound noun "<noun> <noun>"
        if nxt is None or nxt.pos in ("DET", "PRON", "PROPN", "ADV", "ADP", "PUNCT", "NUM", "ADJ", "CCONJ", "SCONJ") or nxt.norm in ("it",):
            return "VERB"
        if nxt.pos in ("NOUN",) and "VERB" in nxt_c:
            return "VERB"
        return "NOUN"
    if prev.pos == "ADP":
        return "VERB" if form == "gerund" else "NOUN"
    if prev.pos in ("VERB", "ADV", "CCONJ", "SCONJ"):
        if nxt and nxt.pos in ("DET", "PRON", "NOUN", "PROPN", "ADJ", "NUM"):
            return "VERB" if prev.pos in ("CCONJ", "SCONJ") and not _has_subject_before(tokens, i) else "NOUN" if prev.pos == "VERB" and nxt.pos not in ("DET",) and False else "VERB" if prev.pos in ("CCONJ", "SCONJ") else "NOUN"
        return "NOUN" if prev.pos == "VERB" else "VERB"
    return c[0]


def _has_subject_before(tokens: list[Token], i: int) -> bool:
    return any(t.pos in ("PRON", "PROPN", "NOUN") for t in tokens[:i])


def participle_forms() -> set[str]:
    return _PARTICIPLES


def verb_form_of(tok: Token) -> str | None:
    va = verb_analysis(tok.norm)
    if va:
        return va[1]
    g = guess_verb(tok.norm)
    return g[1] if g else None


def _build_participles() -> set[str]:
    out = set()
    for lemma in list(VERBS) + list(IRREGULAR_VERBS) + list(EXTRA_VERBS):
        va = [f for f in ((lemma, "x"),)]  # placeholder to keep structure simple
        from .morphology import participle, past
        out.add(participle(lemma)); out.add(past(lemma))
    return out


_PARTICIPLES = _build_participles()


def _finalise(tok: Token, tokens: list[Token], i: int) -> None:
    n, pos = tok.norm, tok.pos
    tok.lemma = n
    if pos == "VERB":
        va = verb_analysis(n)
        if va:
            tok.lemma, form = va[0], va[1]
            tok.feats["known_verb"] = True
        elif n.endswith("s") and singularize(n)[0] in NOUN_VERB:
            tok.lemma, form = singularize(n)[0], "3sg"
        else:
            g = guess_verb(n)
            if g:
                tok.lemma, form = g
            else:
                tok.lemma, form = n, "base"
        tok.feats["form"] = form
        if form in ("base", "past") and n in ("read", "put", "cut", "set", "let", "hit", "hurt", "shut", "cost"):
            tok.feats["form"] = "past" if (i > 0 and tokens[i - 1].pos in ("PROPN", "NOUN") or (i > 0 and tokens[i - 1].norm in ("he", "she", "it"))) else "base"
        if form == "3sg":
            tok.feats["number"] = "sg"
    elif pos == "AUX":
        tok.feats["aux"] = ("be" if n in AUX_BE else "have" if n in AUX_HAVE else "do" if n in AUX_DO else "modal")
        if n in AUX_BE:
            tok.lemma = "be"
            tok.feats["form"] = AUX_BE[n]
            tok.feats["number"] = "pl" if n in ("are", "were", "'re") else "sg"
        elif n in AUX_HAVE:
            tok.lemma = "have"
            tok.feats["form"] = AUX_HAVE[n]
        elif n in AUX_DO:
            tok.lemma = "do"
            tok.feats["form"] = AUX_DO[n]
        elif tok.kind == "clitic":
            nxt = tokens[i + 1] if i + 1 < len(tokens) else None
            if n == "'ll":
                tok.lemma, tok.feats["aux"] = "will", "modal"
            elif n == "'d":
                nxt_va = verb_analysis(nxt.norm) if nxt else None
                tok.lemma = "had" if (nxt_va and nxt_va[1] == "participle") else "would"
                tok.feats["aux"] = "have" if tok.lemma == "had" else "modal"
            elif n == "'ve":
                tok.lemma, tok.feats["aux"], tok.feats["form"] = "have", "have", "present"
            else:
                tok.lemma, tok.feats["aux"], tok.feats["form"] = "be", "be", "present"
                tok.feats["number"] = "pl" if n == "'re" else "sg"
        else:
            tok.feats["modal"] = True
    elif pos == "NOUN":
        lemma, plural = singularize(n)
        tok.lemma = lemma
        tok.feats["number"] = "pl" if plural else "sg"
        if not plural and n in ("people", "police", "staff"):
            tok.feats["number"] = "pl"
    elif pos == "PROPN":
        tok.lemma = tok.text
        tok.feats["number"] = "sg"
        if n in MALE_NAMES:
            tok.feats["gender"] = "m"
        elif n in FEMALE_NAMES:
            tok.feats["gender"] = "f"
    elif pos == "ADJ":
        deg = degree_analysis(n)
        if deg:
            tok.lemma, tok.feats["degree"] = deg[0], deg[1]
        elif n in GRADABLE:
            tok.feats["degree"] = "pos"
        elif guess_degree(n) and i + 1 < len(tokens) and tokens[i + 1].norm == "than":
            base, d = guess_degree(n)  # type: ignore[misc]
            tok.lemma, tok.feats["degree"] = base, d
        else:
            tok.feats["degree"] = "pos"
    elif pos == "PRON":
        tok.feats.update(PRONOUNS.get(n, {}))
    elif pos == "DET":
        if n in POSSESSIVE_DETS:
            tok.feats.update(POSSESSIVE_DETS[n])
            tok.feats["poss"] = True
        else:
            tok.feats.update(DETERMINERS.get(n, {}))
    elif pos == "NUM":
        if tok.kind == "word":
            tok.value = NUMBER_WORDS.get(n)
    elif pos == "PART" and n == "not":
        tok.feats["neg"] = True
    # words like "yesterday" are adverbs for the tagger, time nouns for the semantic layer
    if n in DEICTIC_DAYS and pos in ("ADV", "NOUN"):
        tok.pos = "ADV"
        tok.feats["time"] = True
