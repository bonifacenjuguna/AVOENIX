"""Streaming readers for supported formats. Each yields normalised records and never loads the whole file into memory.

Record kinds:
  ("lemma", synset_id, lemma, pos)            lexical membership of a synset
  ("relation", src, rel, dst, weight)         typed relation between lemmas/concepts (synonym, hypernym, antonym, related, ...)
  ("statement", subject, predicate, object, weight)   a world statement (candidate)
  ("sentence", text)                          a raw text sentence (for co-occurrence statistics)
  ("reject", reason)                          a malformed record (counted in the import report)

WordNet WNDB (``data.noun`` etc.), ConceptNet 5 assertion CSV (tab separated; ``.gz`` accepted) and Wikidata JSONL entity dumps are parsed according to
their published layouts. Only the fixtures in ``tests/fixtures`` have been exercised in this repository (see docs/DATASETS.md).
"""
from __future__ import annotations

import gzip
import io
import json
import re
from pathlib import Path
from typing import Iterator

Record = tuple

PTR_REL = {"@": "hypernym", "@i": "hypernym", "~": "hyponym", "~i": "hyponym", "!": "antonym", "&": "similar", "\\": "derived", "=": "attribute", "#m": "member_of", "#p": "part_of", "%p": "has_part"}
SS_POS = {"n": "noun", "v": "verb", "a": "adj", "s": "adj", "r": "adv"}
CONCEPTNET_REL = {"/r/Synonym": "synonym", "/r/IsA": "hypernym", "/r/Antonym": "antonym", "/r/RelatedTo": "related", "/r/SimilarTo": "similar", "/r/UsedFor": "used_for",
                  "/r/CapableOf": "capable_of", "/r/AtLocation": "at_location", "/r/PartOf": "part_of", "/r/HasProperty": "has_property"}


def _open_text(path: Path) -> io.TextIOBase:
    if str(path).endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, "rt", encoding="utf-8", errors="replace")


def read_wordnet(path: Path, options: dict) -> Iterator[Record]:
    """WNDB data file: ``offset lex_filenum ss_type w_cnt word lex_id [word lex_id...] p_cnt [ptr...] ...| gloss``. ``w_cnt`` is hexadecimal."""
    with _open_text(path) as f:
        for ln, line in enumerate(f, 1):
            if not line.strip() or line.startswith("  "):          # licence header lines are indented
                continue
            try:
                head = line.split("|", 1)[0].split()
                offset, _lex, ss_type, wcnt = head[0], head[1], head[2], int(head[3], 16)
                words = [head[4 + 2 * i].replace("_", " ").lower() for i in range(wcnt)]
                idx = 4 + 2 * wcnt
                pcnt = int(head[idx])
                ptrs = head[idx + 1: idx + 1 + 4 * pcnt]
                if ss_type not in SS_POS or not offset.isdigit():
                    raise ValueError("bad synset type or offset")
                sid = f"{offset}{ss_type if ss_type != 's' else 'a'}"
                pos = SS_POS[ss_type]
                for w in words:
                    yield ("lemma", sid, re.sub(r"\(\w+\)$", "", w), pos)
                for i in range(pcnt):
                    sym, off, p, _st = ptrs[4 * i: 4 * i + 4]
                    rel = PTR_REL.get(sym)
                    if rel:
                        yield ("synset_relation", sid, rel, f"{off}{p if p != 's' else 'a'}", 1.0)
            except (ValueError, IndexError) as e:
                yield ("reject", f"wordnet line {ln}: {e}")


def read_conceptnet(path: Path, options: dict) -> Iterator[Record]:
    """ConceptNet assertions: ``/a/[...]\\t/r/Rel\\t/c/en/start\\t/c/en/end\\t{json with weight}``. English-only edges between single-lemma concepts are kept."""
    lang = options.get("language", "en")
    with _open_text(path) as f:
        for ln, line in enumerate(f, 1):
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 5:
                yield ("reject", f"conceptnet line {ln}: expected 5 columns")
                continue
            _uri, rel, s, e, meta = parts[:5]
            if not (s.startswith(f"/c/{lang}/") and e.startswith(f"/c/{lang}/")):
                continue
            r = CONCEPTNET_REL.get(rel)
            if r is None:
                continue
            try:
                w = float(json.loads(meta).get("weight", 1.0))
            except (ValueError, AttributeError):
                yield ("reject", f"conceptnet line {ln}: bad metadata")
                continue
            a, b = s.split("/")[3].replace("_", " "), e.split("/")[3].replace("_", " ")
            if a == b:
                yield ("reject", f"conceptnet line {ln}: self loop")
                continue
            yield ("relation", a.lower(), r, b.lower(), max(0.0, min(1.0, w / 10.0)))


def read_wikidata(path: Path, options: dict) -> Iterator[Record]:
    """Wikidata entity JSON, one entity per line (optionally wrapped in a ``[`` ... ``]`` array with trailing commas). Emits label statements for the
    properties listed in ``options['properties']`` (default P31 instance-of, P279 subclass-of, P36 capital, P17 country)."""
    props = options.get("properties", {"P31": "instance_of", "P279": "subclass_of", "P36": "capital", "P17": "country"})
    lang = options.get("language", "en")
    labels: dict[str, str] = {}
    pending: list[tuple[str, str, str]] = []
    with _open_text(path) as f:
        for ln, line in enumerate(f, 1):
            line = line.strip().rstrip(",")
            if line in ("[", "]", ""):
                continue
            try:
                ent = json.loads(line)
                qid = ent["id"]
                lab = ent.get("labels", {}).get(lang, {}).get("value")
                if lab:
                    labels[qid] = lab
                for pid, pred in props.items():
                    for cl in ent.get("claims", {}).get(pid, []):
                        dv = cl.get("mainsnak", {}).get("datavalue", {}).get("value", {})
                        if isinstance(dv, dict) and "id" in dv:
                            pending.append((qid, pred, dv["id"]))
            except (ValueError, KeyError, AttributeError, TypeError) as e:
                yield ("reject", f"wikidata line {ln}: {e}")
    for s, p, o in pending:
        if s in labels and o in labels:
            yield ("statement", labels[s], p, labels[o], 0.6)
        else:
            yield ("reject", "wikidata: statement refers to an entity without an English label")


def read_text(path: Path, options: dict) -> Iterator[Record]:
    """Plain text: one sentence per line or sentences separated by .!? ; blank lines ignored."""
    with _open_text(path) as f:
        for line in f:
            for s in re.split(r"(?<=[.!?])\s+", line.strip()):
                if len(s) >= 3:
                    yield ("sentence", s)


READERS = {"wordnet_wndb": read_wordnet, "conceptnet_csv": read_conceptnet, "wikidata_jsonl": read_wikidata, "text_corpus": read_text}
