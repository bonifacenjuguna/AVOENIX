"""Language-neutral concept inventory.

Concept identifiers are the vocabulary of ACR. English words map *onto* these identifiers
(see ``engines/language/en``); nothing here is English. A future language interface would
provide its own lexicon over the same inventory.

Only genuinely structural knowledge lives here (taxonomy of node classes, logical
properties of relations, dimensions of comparison). It is not world knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ConceptInfo:
    id: str
    kind: str                                 # class | relation | property | dimension | action | role
    parents: tuple[str, ...] = ()
    transitive: bool = False
    symmetric: bool = False
    functional: bool = False                  # at most one value per subject
    inverse_of: str | None = None
    # Event/action argument structure (language neutral)
    frame: tuple[str, ...] = ()               # roles typically present
    animate_roles: tuple[str, ...] = ()       # roles that must be filled by animate beings
    meta: dict = field(default_factory=dict, hash=False, compare=False)


_REGISTRY: dict[str, ConceptInfo] = {}


def register(info: ConceptInfo) -> ConceptInfo:
    _REGISTRY[info.id] = info
    return info


def get(concept_id: str) -> ConceptInfo | None:
    return _REGISTRY.get(concept_id)


def all_concepts() -> list[ConceptInfo]:
    return list(_REGISTRY.values())


def ancestors(concept_id: str) -> set[str]:
    seen: set[str] = set()
    stack = [concept_id]
    while stack:
        current = stack.pop()
        info = _REGISTRY.get(current)
        if not info:
            continue
        for parent in info.parents:
            if parent not in seen:
                seen.add(parent)
                stack.append(parent)
    return seen


def is_a(child: str, parent: str) -> bool:
    return child == parent or parent in ancestors(child)


def is_functional(concept_id: str) -> bool:
    info = _REGISTRY.get(concept_id)
    return bool(info and info.functional)


def is_transitive(concept_id: str) -> bool:
    info = _REGISTRY.get(concept_id)
    return bool(info and info.transitive)


def is_symmetric(concept_id: str) -> bool:
    info = _REGISTRY.get(concept_id)
    return bool(info and info.symmetric)


# ---- node classes ---------------------------------------------------------------------
for _cid, _parents in [
    ("class.entity", ()),
    ("class.person", ("class.animate",)),
    ("class.animate", ("class.entity",)),
    ("class.animal", ("class.animate",)),
    ("class.thing", ("class.entity",)),
    ("class.place", ("class.entity",)),
    ("class.organization", ("class.entity",)),
    ("class.abstract", ("class.entity",)),
    ("class.time_unit", ("class.abstract",)),
]:
    register(ConceptInfo(_cid, "class", _parents))

# ---- relations ------------------------------------------------------------------------
register(ConceptInfo("rel.is_a", "relation", transitive=True, meta={"roles": ("subject", "object")}))
register(ConceptInfo("rel.identical", "relation", symmetric=True, transitive=True))
register(ConceptInfo("rel.exceeds", "relation", transitive=True,
                     meta={"roles": ("greater", "lesser", "dimension")}))
register(ConceptInfo("rel.equal_on", "relation", symmetric=True, transitive=True,
                     meta={"roles": ("first", "second", "dimension")}))
register(ConceptInfo("rel.extreme", "relation", meta={"roles": ("subject", "dimension", "pole", "domain")}))
register(ConceptInfo("rel.part_of", "relation", transitive=True))
register(ConceptInfo("rel.located_in", "relation", transitive=True))
register(ConceptInfo("rel.capital_of", "relation", functional=False, meta={"roles": ("subject", "object")}))
register(ConceptInfo("rel.owns", "relation"))
register(ConceptInfo("rel.has_property", "relation", meta={"roles": ("subject", "property")}))
register(ConceptInfo("rel.has_name", "relation", functional=True, meta={"roles": ("subject", "value")}))
register(ConceptInfo("rel.knows", "relation"))
register(ConceptInfo("rel.likes", "relation"))
register(ConceptInfo("rel.causes", "relation", transitive=True))
register(ConceptInfo("rel.rank", "relation", meta={"roles": ("subject", "position", "dimension")}))

# ---- dimensions of comparison (each paired with a numeric property) -----------------
for _dim, _prop, _unit in [
    ("dim.age", "prop.age", "year"),
    ("dim.height", "prop.height", "meter"),
    ("dim.length", "prop.length", "meter"),
    ("dim.weight", "prop.weight", "kilogram"),
    ("dim.speed", "prop.speed", "meter_per_second"),
    ("dim.size", "prop.size", None),
    ("dim.wealth", "prop.wealth", None),
    ("dim.price", "prop.price", None),
    ("dim.temperature", "prop.temperature", "celsius"),
    ("dim.strength", "prop.strength", None),
    ("dim.intelligence", "prop.intelligence", None),
    ("dim.difficulty", "prop.difficulty", None),
    ("dim.quality", "prop.quality", None),
    ("dim.elevation", "prop.elevation", "meter"),
    ("dim.depth", "prop.depth", "meter"),
    ("dim.width", "prop.width", "meter"),
    ("dim.distance", "prop.distance", "meter"),
    ("dim.score", "prop.score", None),
]:
    register(ConceptInfo(_dim, "dimension", meta={"property": _prop, "unit": _unit}))
    register(ConceptInfo(_prop, "property", functional=True, meta={"dimension": _dim, "unit": _unit}))

register(ConceptInfo("prop.count", "property", functional=False))

# ---- actions (argument structure only; wording lives in the language lexicon) --------
_ACTIONS = {
    #  id                     frame                                         animate roles
    "act.give":    (("agent", "recipient", "theme"),                        ("agent", "recipient")),
    "act.take":    (("agent", "theme", "source"),                           ("agent",)),
    "act.receive": (("recipient", "theme", "source"),                       ("recipient",)),
    "act.buy":     (("agent", "theme", "source"),                           ("agent",)),
    "act.sell":    (("agent", "theme", "recipient"),                        ("agent",)),
    "act.need":    (("experiencer", "theme"),                               ("experiencer",)),
    "act.want":    (("experiencer", "theme"),                               ("experiencer",)),
    "act.like":    (("experiencer", "stimulus"),                            ("experiencer",)),
    "act.love":    (("experiencer", "stimulus"),                            ("experiencer",)),
    "act.hate":    (("experiencer", "stimulus"),                            ("experiencer",)),
    "act.know":    (("experiencer", "theme"),                               ("experiencer",)),
    "act.believe": (("experiencer", "theme"),                               ("experiencer",)),
    "act.see":     (("experiencer", "stimulus"),                            ("experiencer",)),
    "act.have":    (("agent", "theme"),                                     ()),
    "act.lose":    (("agent", "theme"),                                     ("agent",)),
    "act.find":    (("agent", "theme"),                                     ("agent",)),
    "act.eat":     (("agent", "theme"),                                     ("agent",)),
    "act.make":    (("agent", "theme"),                                     ("agent",)),
    "act.read":    (("agent", "theme"),                                     ("agent",)),
    "act.write":   (("agent", "theme", "recipient"),                        ("agent",)),
    "act.say":     (("agent", "theme", "recipient"),                        ("agent",)),
    "act.tell":    (("agent", "recipient", "theme"),                        ("agent", "recipient")),
    "act.ask":     (("agent", "recipient", "theme"),                        ("agent", "recipient")),
    "act.help":    (("agent", "beneficiary"),                               ("agent",)),
    "act.go":      (("agent", "goal", "source"),                            ("agent",)),
    "act.arrive":  (("agent", "goal"),                                      ("agent",)),
    "act.leave":   (("agent", "source"),                                    ("agent",)),
    "act.come":    (("agent", "goal"),                                      ("agent",)),
    "act.run":     (("agent",),                                             ("agent",)),
    "act.walk":    (("agent",),                                             ("agent",)),
    "act.open":    (("agent", "theme"),                                     ("agent",)),
    "act.close":   (("agent", "theme"),                                     ("agent",)),
    "act.start":   (("agent", "theme"),                                     ("agent",)),
    "act.finish":  (("agent", "theme"),                                     ("agent",)),
    "act.break":   (("agent", "theme"),                                     ()),
    "act.use":     (("agent", "theme"),                                     ("agent",)),
    "act.learn":   (("agent", "theme"),                                     ("agent",)),
    "act.teach":   (("agent", "recipient", "theme"),                        ("agent", "recipient")),
    "act.study":   (("agent", "theme"),                                     ("agent",)),
    "act.visit":   (("agent", "goal"),                                      ("agent",)),
    "act.call":    (("agent", "recipient"),                                 ("agent",)),
    "act.send":    (("agent", "recipient", "theme"),                        ("agent",)),
    "act.bring":   (("agent", "recipient", "theme"),                        ("agent",)),
    "act.show":    (("agent", "recipient", "theme"),                        ("agent", "recipient")),
    "act.play":    (("agent", "theme"),                                     ("agent",)),
    "act.work":    (("agent",),                                             ("agent",)),
    "act.live":    (("agent", "location"),                                  ("agent",)),
    "act.born":    (("theme", "location"),                                  ()),
    "act.cook":    (("agent", "theme"),                                     ("agent",)),
    "act.drive":   (("agent", "theme"),                                     ("agent",)),
    "act.pay":     (("agent", "recipient", "theme"),                        ("agent",)),
    "act.spend":   (("agent", "theme"),                                     ("agent",)),
    "act.plan":    (("agent", "theme"),                                     ("agent",)),
    "act.remember": (("experiencer", "theme"),                              ("experiencer",)),
    "act.forget":  (("experiencer", "theme"),                               ("experiencer",)),
    "act.think":   (("experiencer", "theme"),                               ("experiencer",)),
    "act.feel":    (("experiencer", "theme"),                               ("experiencer",)),
    "act.try":     (("agent", "theme"),                                     ("agent",)),
    "act.build":   (("agent", "theme"),                                     ("agent",)),
    "act.publish": (("agent", "theme"),                                     ("agent",)),
    "act.research": (("agent", "theme"),                                    ("agent",)),
    "act.submit":  (("agent", "theme", "recipient"),                        ("agent",)),
    "act.prepare": (("agent", "theme"),                                     ("agent",)),
    "act.review":  (("agent", "theme"),                                     ("agent",)),
    "act.test":    (("agent", "theme"),                                     ("agent",)),
    "act.deploy":  (("agent", "theme"),                                     ("agent",)),
    "act.design":  (("agent", "theme"),                                     ("agent",)),
    "act.draft":   (("agent", "theme"),                                     ("agent",)),
}
for _aid, (_frame, _anim) in _ACTIONS.items():
    register(ConceptInfo(_aid, "action", frame=_frame, animate_roles=_anim))

#: Roles accepted in Event.roles (extensible; unknown roles produce warnings, not errors)
EVENT_ROLES = frozenset({
    "agent", "patient", "theme", "recipient", "experiencer", "stimulus", "beneficiary",
    "instrument", "source", "goal", "comitative", "cause", "attribute", "content", "topic",
    "measure", "value", "owner", "owned", "location", "manner",
})
