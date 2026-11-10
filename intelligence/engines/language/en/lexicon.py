"""English lexicon: closed-class words, verbs, gradable adjectives, time words, names.

Everything here is authored by the AVOENIX project (no corpus, no downloaded resource).
Open-class coverage is intentionally modest; words outside the lexicon are handled by
morphological and contextual rules in the tagger rather than rejected.
"""

from __future__ import annotations

# ------------------------------------------------------------------------------------
# Closed classes
# ------------------------------------------------------------------------------------
DETERMINERS = {
    "a": {"definite": False, "number": "sg"}, "an": {"definite": False, "number": "sg"},
    "the": {"definite": True}, "this": {"definite": True, "number": "sg", "deictic": "near"},
    "that": {"definite": True, "number": "sg", "deictic": "far"},
    "these": {"definite": True, "number": "pl", "deictic": "near"},
    "those": {"definite": True, "number": "pl", "deictic": "far"},
    "some": {"quant": "some"}, "any": {"quant": "any"}, "no": {"quant": "no"},
    "all": {"quant": "all"}, "every": {"quant": "all", "number": "sg"}, "each": {"quant": "all", "number": "sg"},
    "most": {"quant": "most"}, "few": {"quant": "few"}, "many": {"quant": "many"},
    "much": {"quant": "much"}, "another": {"definite": False, "number": "sg"}, "both": {"quant": "both"},
    "either": {"quant": "either"}, "neither": {"quant": "neither"}, "which": {"wh": True}, "what": {"wh": True},
    "whose": {"wh": True, "possessive": True},
}
POSSESSIVE_DETS = {
    "my": {"person": 1, "number": "sg"}, "your": {"person": 2}, "his": {"person": 3, "gender": "m", "number": "sg"},
    "her": {"person": 3, "gender": "f", "number": "sg"}, "its": {"person": 3, "gender": "n", "number": "sg"},
    "our": {"person": 1, "number": "pl"}, "their": {"person": 3, "number": "pl"},
}
# pronoun -> features (case, person, number, gender, animacy)
PRONOUNS = {
    "i": dict(person=1, number="sg", case="nom"), "me": dict(person=1, number="sg", case="acc"),
    "myself": dict(person=1, number="sg", case="refl"),
    "we": dict(person=1, number="pl", case="nom"), "us": dict(person=1, number="pl", case="acc"),
    "you": dict(person=2, case="any"), "yourself": dict(person=2, number="sg", case="refl"),
    "he": dict(person=3, number="sg", gender="m", animacy="animate", case="nom"),
    "him": dict(person=3, number="sg", gender="m", animacy="animate", case="acc"),
    "himself": dict(person=3, number="sg", gender="m", animacy="animate", case="refl"),
    "her": dict(person=3, number="sg", gender="f", animacy="animate", case="acc"),
    "she": dict(person=3, number="sg", gender="f", animacy="animate", case="nom"),
    "herself": dict(person=3, number="sg", gender="f", animacy="animate", case="refl"),
    "it": dict(person=3, number="sg", gender="n", animacy="inanimate", case="any"),
    "itself": dict(person=3, number="sg", gender="n", animacy="inanimate", case="refl"),
    "they": dict(person=3, number="pl", case="nom"), "them": dict(person=3, number="pl", case="acc"),
    "themselves": dict(person=3, number="pl", case="refl"),
    "who": dict(wh=True, animacy="animate"), "whom": dict(wh=True, animacy="animate"),
    "what": dict(wh=True), "which": dict(wh=True),
    "this": dict(person=3, number="sg", deictic="near"), "that": dict(person=3, number="sg", deictic="far"),
    "these": dict(person=3, number="pl", deictic="near"), "those": dict(person=3, number="pl", deictic="far"),
    "someone": dict(person=3, number="sg", animacy="animate", indefinite=True),
    "somebody": dict(person=3, number="sg", animacy="animate", indefinite=True),
    "anyone": dict(person=3, number="sg", animacy="animate", indefinite=True),
    "everyone": dict(person=3, number="sg", animacy="animate", quant="all"),
    "everybody": dict(person=3, number="sg", animacy="animate", quant="all"),
    "nobody": dict(person=3, number="sg", animacy="animate", quant="no"),
    "something": dict(person=3, number="sg", animacy="inanimate", indefinite=True),
    "anything": dict(person=3, number="sg", animacy="inanimate", indefinite=True),
    "everything": dict(person=3, number="sg", animacy="inanimate", quant="all"),
    "nothing": dict(person=3, number="sg", animacy="inanimate", quant="no"),
    "one": dict(person=3, number="sg", generic=True),
    "ones": dict(person=3, number="pl", generic=True),
}
WH_WORDS = {"who", "whom", "whose", "what", "which", "when", "where", "why", "how"}
PREPOSITIONS = {
    "in", "on", "at", "to", "for", "with", "from", "by", "of", "about", "into", "onto", "over", "under",
    "between", "among", "through", "during", "before", "after", "since", "until", "till", "near", "behind",
    "beside", "against", "without", "within", "across", "around", "toward", "towards", "up", "down", "off",
    "than", "as", "like", "per", "via", "inside", "outside", "above", "below", "beyond", "despite", "except",
}
CCONJ = {"and", "or", "but", "nor", "yet", "so"}
SCONJ = {"because", "if", "when", "while", "although", "though", "unless", "whereas", "once", "whether", "since",
         "after", "before", "until", "as", "that", "so"}
SUBORDINATORS_CLAUSE = {"because", "if", "while", "although", "though", "unless", "whereas", "once", "when",
                        "since", "after", "before", "until", "whether"}
AUX_BE = {"am": "present", "is": "present", "are": "present", "was": "past", "were": "past", "be": "base",
          "been": "participle", "being": "gerund", "'m": "present", "'re": "present"}
AUX_HAVE = {"have": "present", "has": "present", "had": "past", "having": "gerund"}
AUX_DO = {"do": "present", "does": "present", "did": "past"}
MODALS = {"can", "could", "will", "would", "shall", "should", "may", "might", "must", "ought"}
NEGATORS = {"not", "n't", "never", "no", "none", "nobody", "nothing", "neither", "nor", "without", "cannot"}
INTENSIFIERS = {"very": 1.4, "really": 1.4, "extremely": 1.8, "incredibly": 1.8, "so": 1.3, "too": 1.2,
                "quite": 1.15, "totally": 1.5, "absolutely": 1.7, "highly": 1.4, "super": 1.5, "truly": 1.4,
                "deeply": 1.5, "especially": 1.3, "pretty": 1.15}
DIMINISHERS = {"slightly": 0.5, "somewhat": 0.7, "barely": 0.4, "a bit": 0.7, "kind": 0.8, "little": 0.7,
               "fairly": 0.85, "rather": 0.9, "hardly": 0.4, "almost": 0.8}
ADVERBS_COMMON = {
    "very", "really", "quite", "too", "also", "just", "still", "already", "always", "often", "sometimes",
    "usually", "never", "now", "then", "here", "there", "soon", "later", "again", "ever", "even", "only",
    "yesterday", "today", "tomorrow", "tonight", "recently", "currently", "quickly", "slowly", "well",
    "almost", "maybe", "perhaps", "together", "however", "therefore", "thus", "instead", "else", "far",
    "away", "back", "once", "twice", "enough", "rather", "somewhat", "slightly", "extremely", "absolutely",
    "totally", "super", "pretty", "fairly", "barely", "hardly", "truly", "deeply", "highly", "especially",
    "incredibly", "so", "right", "please", "yet", "actually", "honestly", "basically",
}
INTERJECTIONS = {
    # word -> (act, formality 0..1, warmth 0..1)
    "hello": ("greet", 0.6, 0.5), "hi": ("greet", 0.3, 0.6), "hey": ("greet", 0.1, 0.6), "hiya": ("greet", 0.1, 0.7),
    "howdy": ("greet", 0.1, 0.6), "greetings": ("greet", 0.9, 0.5), "yo": ("greet", 0.0, 0.4), "sup": ("greet", 0.0, 0.4),
    "bye": ("farewell", 0.3, 0.5), "goodbye": ("farewell", 0.7, 0.5), "cheers": ("thank_or_farewell", 0.3, 0.6),
    "thanks": ("thank", 0.3, 0.7), "thank": ("thank", 0.6, 0.7), "thx": ("thank", 0.0, 0.6),
    "sorry": ("apologize", 0.5, 0.6), "apologies": ("apologize", 0.8, 0.5), "pardon": ("apologize", 0.7, 0.4),
    "please": ("polite", 0.6, 0.5), "ok": ("acknowledge", 0.3, 0.3), "okay": ("acknowledge", 0.3, 0.3),
    "yes": ("affirm", 0.4, 0.3), "yeah": ("affirm", 0.1, 0.4), "yep": ("affirm", 0.0, 0.4), "sure": ("affirm", 0.3, 0.4),
    "no": ("deny", 0.4, 0.2), "nope": ("deny", 0.0, 0.2), "nah": ("deny", 0.0, 0.2),
    "wow": ("exclaim", 0.2, 0.6), "oh": ("exclaim", 0.2, 0.3), "ah": ("exclaim", 0.2, 0.3), "oops": ("exclaim", 0.1, 0.3),
    "great": ("exclaim", 0.3, 0.6), "awesome": ("exclaim", 0.1, 0.7), "cool": ("exclaim", 0.1, 0.5),
    "welcome": ("greet", 0.6, 0.7), "congratulations": ("exclaim", 0.7, 0.7), "congrats": ("exclaim", 0.2, 0.7),
}
NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "half": 0.5, "dozen": 12,
}
SCALE_WORDS = {"hundred": 100, "thousand": 1000, "million": 1_000_000, "billion": 1_000_000_000}
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
            "eighth": 8, "ninth": 9, "tenth": 10, "last": -1, "previous": -2, "next": 1, "final": -1}
ARITH_WORDS = {
    "plus": "add", "added": "add", "minus": "sub", "subtract": "sub", "subtracted": "sub",
    "times": "mul", "multiplied": "mul", "divided": "div", "over": "div",
}

# ------------------------------------------------------------------------------------
# Time vocabulary
# ------------------------------------------------------------------------------------
DEICTIC_DAYS = {"yesterday": -1, "today": 0, "tomorrow": 1, "tonight": 0}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
TIME_UNITS = {"second": "second", "minute": "minute", "hour": "hour", "day": "day", "week": "week", "month": "month",
              "year": "year", "morning": "part_of_day", "afternoon": "part_of_day", "evening": "part_of_day",
              "night": "part_of_day", "weekend": "week", "decade": "year"}
TIME_FREQUENCY = {"daily", "weekly", "monthly", "yearly", "annually"}

# ------------------------------------------------------------------------------------
# Verbs: lemma -> (concept, frame, forms)
#   frame: "intr" | "tr" | "ditr" (dative alternation) | "copula" | "cog" (clausal complement) | "tr_inf"
# ------------------------------------------------------------------------------------
IRREGULAR_VERBS = {
    # lemma: (past, participle)
    "be": ("was", "been"), "have": ("had", "had"), "do": ("did", "done"), "go": ("went", "gone"),
    "give": ("gave", "given"), "take": ("took", "taken"), "get": ("got", "gotten"), "make": ("made", "made"),
    "see": ("saw", "seen"), "know": ("knew", "known"), "think": ("thought", "thought"), "come": ("came", "come"),
    "say": ("said", "said"), "tell": ("told", "told"), "buy": ("bought", "bought"), "sell": ("sold", "sold"),
    "eat": ("ate", "eaten"), "find": ("found", "found"), "lose": ("lost", "lost"), "bring": ("brought", "brought"),
    "send": ("sent", "sent"), "write": ("wrote", "written"), "read": ("read", "read"), "run": ("ran", "run"),
    "leave": ("left", "left"), "feel": ("felt", "felt"), "keep": ("kept", "kept"), "begin": ("began", "begun"),
    "break": ("broke", "broken"), "build": ("built", "built"), "drive": ("drove", "driven"), "pay": ("paid", "paid"),
    "spend": ("spent", "spent"), "teach": ("taught", "taught"), "show": ("showed", "shown"), "meet": ("met", "met"),
    "sit": ("sat", "sat"), "stand": ("stood", "stood"), "speak": ("spoke", "spoken"), "understand": ("understood", "understood"),
    "forget": ("forgot", "forgotten"), "hold": ("held", "held"), "put": ("put", "put"), "set": ("set", "set"),
    "let": ("let", "let"), "cut": ("cut", "cut"), "hit": ("hit", "hit"), "hurt": ("hurt", "hurt"), "win": ("won", "won"),
    "become": ("became", "become"), "choose": ("chose", "chosen"), "fall": ("fell", "fallen"), "grow": ("grew", "grown"),
    "hear": ("heard", "heard"), "lead": ("led", "led"), "sleep": ("slept", "slept"), "swim": ("swam", "swum"),
    "wear": ("wore", "worn"), "draw": ("drew", "drawn"), "drink": ("drank", "drunk"), "fly": ("flew", "flown"),
    "sing": ("sang", "sung"), "throw": ("threw", "thrown"), "catch": ("caught", "caught"), "fight": ("fought", "fought"),
    "bear": ("bore", "borne"), "lend": ("lent", "lent"), "rise": ("rose", "risen"), "ride": ("rode", "ridden"),
    "steal": ("stole", "stolen"), "wake": ("woke", "woken"), "seek": ("sought", "sought"),
}

# lemma -> (concept id, frame). Synonyms share a concept id (paraphrase handling).
VERBS: dict[str, tuple[str, str]] = {
    "give": ("act.give", "ditr"), "hand": ("act.give", "ditr"), "donate": ("act.give", "ditr"), "lend": ("act.give", "ditr"),
    "offer": ("act.give", "ditr"), "present": ("act.give", "ditr"), "award": ("act.give", "ditr"),
    "take": ("act.take", "tr"), "grab": ("act.take", "tr"), "seize": ("act.take", "tr"),
    "receive": ("act.receive", "tr"), "get": ("act.receive", "tr"), "obtain": ("act.receive", "tr"), "acquire": ("act.receive", "tr"),
    "buy": ("act.buy", "tr"), "purchase": ("act.buy", "tr"), "sell": ("act.sell", "ditr"),
    "need": ("act.need", "tr_inf"), "require": ("act.need", "tr"),
    "want": ("act.want", "tr_inf"), "desire": ("act.want", "tr"), "wish": ("act.want", "tr_inf"),
    "like": ("act.like", "tr"), "enjoy": ("act.like", "tr"), "love": ("act.love", "tr"), "adore": ("act.love", "tr"),
    "hate": ("act.hate", "tr"), "dislike": ("act.hate", "tr"), "prefer": ("act.like", "tr"),
    "know": ("act.know", "cog"), "believe": ("act.believe", "cog"), "see": ("act.see", "tr"), "notice": ("act.see", "tr"),
    "watch": ("act.see", "tr"), "think": ("act.think", "cog"), "feel": ("act.feel", "cog"), "remember": ("act.remember", "cog"),
    "forget": ("act.forget", "cog"), "understand": ("act.know", "cog"),
    "have": ("act.have", "tr"), "own": ("act.have", "tr"), "possess": ("act.have", "tr"),
    "lose": ("act.lose", "tr"), "find": ("act.find", "tr"), "discover": ("act.find", "tr"),
    "eat": ("act.eat", "tr"), "consume": ("act.eat", "tr"), "drink": ("act.eat", "tr"),
    "make": ("act.make", "tr"), "create": ("act.make", "tr"), "produce": ("act.make", "tr"), "build": ("act.build", "tr"),
    "construct": ("act.build", "tr"), "read": ("act.read", "tr"), "write": ("act.write", "tr"),
    "say": ("act.say", "cog"), "tell": ("act.tell", "ditr"), "ask": ("act.ask", "ditr"),
    "help": ("act.help", "tr"), "assist": ("act.help", "tr"), "aid": ("act.help", "tr"),
    "go": ("act.go", "intr"), "travel": ("act.go", "intr"), "arrive": ("act.arrive", "intr"), "reach": ("act.arrive", "tr"),
    "leave": ("act.leave", "tr"), "depart": ("act.leave", "intr"), "come": ("act.come", "intr"),
    "run": ("act.run", "intr"), "walk": ("act.walk", "intr"), "open": ("act.open", "tr"), "close": ("act.close", "tr"),
    "start": ("act.start", "tr"), "begin": ("act.start", "tr"), "finish": ("act.finish", "tr"), "complete": ("act.finish", "tr"),
    "end": ("act.finish", "tr"), "break": ("act.break", "tr"), "use": ("act.use", "tr"), "learn": ("act.learn", "tr"),
    "teach": ("act.teach", "ditr"), "study": ("act.study", "tr"), "visit": ("act.visit", "tr"), "call": ("act.call", "tr"),
    "phone": ("act.call", "tr"), "send": ("act.send", "ditr"), "bring": ("act.bring", "ditr"), "show": ("act.show", "ditr"),
    "play": ("act.play", "tr"), "work": ("act.work", "intr"), "live": ("act.live", "intr"), "cook": ("act.cook", "tr"),
    "drive": ("act.drive", "tr"), "pay": ("act.pay", "ditr"), "spend": ("act.spend", "tr"), "plan": ("act.plan", "tr"),
    "try": ("act.try", "tr_inf"), "publish": ("act.publish", "tr"), "research": ("act.research", "tr"),
    "submit": ("act.submit", "ditr"), "prepare": ("act.prepare", "tr"), "review": ("act.review", "tr"),
    "test": ("act.test", "tr"), "deploy": ("act.deploy", "tr"), "design": ("act.design", "tr"), "draft": ("act.draft", "tr"),
    "borrow": ("act.take", "tr"), "keep": ("act.have", "tr"), "wait": ("act.wait", "intr"), "stay": ("act.stay", "intr"),
    "sleep": ("act.sleep", "intr"), "sit": ("act.sit", "intr"), "stand": ("act.stand", "intr"), "smile": ("act.smile", "intr"),
    "laugh": ("act.laugh", "intr"), "cry": ("act.cry", "intr"), "fall": ("act.fall", "intr"), "win": ("act.win", "tr"),
    "meet": ("act.meet", "tr"), "join": ("act.join", "tr"), "clean": ("act.clean", "tr"), "fix": ("act.fix", "tr"),
    "repair": ("act.fix", "tr"), "move": ("act.move", "tr"), "turn": ("act.turn", "tr"), "carry": ("act.carry", "tr"),
    "throw": ("act.throw", "tr"), "catch": ("act.catch", "tr"), "pick": ("act.pick", "tr"), "put": ("act.put", "tr"),
    "listen": ("act.listen", "intr"), "speak": ("act.speak", "intr"), "talk": ("act.speak", "intr"), "answer": ("act.answer", "tr"),
    "explain": ("act.explain", "tr"), "mean": ("act.mean", "tr"), "become": ("act.become", "copula_like"),
    "seem": ("act.seem", "copula_like"), "look": ("act.look", "copula_like"), "remain": ("act.remain", "copula_like"),
    "exist": ("act.exist", "intr"), "happen": ("act.happen", "intr"), "matter": ("act.matter", "intr"),
    "born": ("act.born", "tr"), "marry": ("act.marry", "tr"), "invite": ("act.invite", "tr"), "thank": ("act.thank", "tr"),
    "remind": ("act.remind", "tr"), "save": ("act.save", "tr"), "delete": ("act.delete", "tr"), "create_": ("act.make", "tr"),
    "add": ("act.add", "tr"), "remove": ("act.remove", "tr"), "change": ("act.change", "tr"), "improve": ("act.improve", "tr"),
}
#: lemmas whose experiencer must be animate (used for pronoun selection)
COGNITIVE_VERBS = {"act.need", "act.want", "act.like", "act.love", "act.hate", "act.know", "act.believe", "act.think",
                   "act.feel", "act.remember", "act.forget", "act.see"}
#: verbs that may take a "to"-infinitive complement
INF_COMPLEMENT = {"want", "need", "try", "plan", "like", "love", "hate", "wish", "decide", "hope", "expect", "prefer",
                  "start", "begin", "learn", "forget", "remember", "promise", "offer", "intend", "continue"}
#: the verb ``decide``, ``hope`` and friends share no concept of their own (kept as provisional)
EXTRA_VERBS = {"decide", "hope", "expect", "promise", "intend", "continue", "stop", "agree", "refuse", "manage",
               "seem", "appear", "enjoy"}

# ------------------------------------------------------------------------------------
# Gradable adjectives: base -> (dimension, pole, comparative, superlative)
#   pole +1: names the high end of the dimension; -1: the low end
# ------------------------------------------------------------------------------------
GRADABLE: dict[str, tuple[str, int, str | None, str | None]] = {
    "old": ("dim.age", +1, "older", "oldest"), "young": ("dim.age", -1, "younger", "youngest"),
    "new": ("dim.age", -1, "newer", "newest"), "elderly": ("dim.age", +1, None, None),
    "tall": ("dim.height", +1, "taller", "tallest"), "short": ("dim.height", -1, "shorter", "shortest"),
    "long": ("dim.length", +1, "longer", "longest"),
    "heavy": ("dim.weight", +1, "heavier", "heaviest"), "light": ("dim.weight", -1, "lighter", "lightest"),
    "fast": ("dim.speed", +1, "faster", "fastest"), "quick": ("dim.speed", +1, "quicker", "quickest"),
    "slow": ("dim.speed", -1, "slower", "slowest"),
    "big": ("dim.size", +1, "bigger", "biggest"), "large": ("dim.size", +1, "larger", "largest"),
    "huge": ("dim.size", +1, None, None), "small": ("dim.size", -1, "smaller", "smallest"),
    "tiny": ("dim.size", -1, None, None), "little": ("dim.size", -1, "littler", "littlest"),
    "rich": ("dim.wealth", +1, "richer", "richest"), "poor": ("dim.wealth", -1, "poorer", "poorest"),
    "wealthy": ("dim.wealth", +1, "wealthier", "wealthiest"),
    "expensive": ("dim.price", +1, "more expensive", "most expensive"), "pricey": ("dim.price", +1, "pricier", "priciest"),
    "cheap": ("dim.price", -1, "cheaper", "cheapest"),
    "hot": ("dim.temperature", +1, "hotter", "hottest"), "warm": ("dim.temperature", +1, "warmer", "warmest"),
    "cold": ("dim.temperature", -1, "colder", "coldest"), "cool": ("dim.temperature", -1, "cooler", "coolest"),
    "strong": ("dim.strength", +1, "stronger", "strongest"), "weak": ("dim.strength", -1, "weaker", "weakest"),
    "smart": ("dim.intelligence", +1, "smarter", "smartest"), "intelligent": ("dim.intelligence", +1, "more intelligent", "most intelligent"),
    "clever": ("dim.intelligence", +1, "cleverer", "cleverest"), "dumb": ("dim.intelligence", -1, "dumber", "dumbest"),
    "hard": ("dim.difficulty", +1, "harder", "hardest"), "difficult": ("dim.difficulty", +1, "more difficult", "most difficult"),
    "easy": ("dim.difficulty", -1, "easier", "easiest"), "simple": ("dim.difficulty", -1, "simpler", "simplest"),
    "good": ("dim.quality", +1, "better", "best"), "bad": ("dim.quality", -1, "worse", "worst"),
    "high": ("dim.elevation", +1, "higher", "highest"), "low": ("dim.elevation", -1, "lower", "lowest"),
    "deep": ("dim.depth", +1, "deeper", "deepest"), "shallow": ("dim.depth", -1, "shallower", "shallowest"),
    "wide": ("dim.width", +1, "wider", "widest"), "narrow": ("dim.width", -1, "narrower", "narrowest"),
    "far": ("dim.distance", +1, "farther", "farthest"), "close": ("dim.distance", -1, "closer", "closest"),
    "near": ("dim.distance", -1, "nearer", "nearest"),
}
# Irregular comparative forms that cannot be derived from the base by suffixing
COMPARATIVE_FORMS: dict[str, tuple[str, str]] = {}      # surface -> (base, "cmp"|"sup")
for _b, (_d, _p, _c, _s) in GRADABLE.items():
    if _c and " " not in _c:
        COMPARATIVE_FORMS[_c] = (_b, "cmp")
    if _s and " " not in _s:
        COMPARATIVE_FORMS[_s] = (_b, "sup")
COMPARATIVE_FORMS.update({"further": ("far", "cmp"), "furthest": ("far", "sup"), "elder": ("old", "cmp"), "eldest": ("old", "sup")})
#: the unit "X years old" gives an age; "X cm tall" gives a height, etc.
MEASURE_ADJECTIVES = {"old": "dim.age", "tall": "dim.height", "long": "dim.length", "wide": "dim.width",
                      "deep": "dim.depth", "high": "dim.elevation", "heavy": "dim.weight"}
UNITS = {
    "year": ("year", "dim.age"), "years": ("year", "dim.age"), "month": ("month", None), "months": ("month", None),
    "day": ("day", None), "days": ("day", None), "week": ("week", None), "weeks": ("week", None),
    "hour": ("hour", None), "hours": ("hour", None), "minute": ("minute", None), "minutes": ("minute", None),
    "second": ("second", None), "seconds": ("second", None),
    "meter": ("meter", None), "meters": ("meter", None), "metre": ("meter", None), "metres": ("meter", None),
    "m": ("meter", None), "cm": ("centimeter", None), "centimeter": ("centimeter", None), "centimeters": ("centimeter", None),
    "km": ("kilometer", None), "kilometer": ("kilometer", None), "kilometers": ("kilometer", None),
    "mile": ("mile", None), "miles": ("mile", None), "foot": ("foot", None), "feet": ("foot", None), "ft": ("foot", None),
    "inch": ("inch", None), "inches": ("inch", None), "kg": ("kilogram", "dim.weight"), "kilogram": ("kilogram", "dim.weight"),
    "kilograms": ("kilogram", "dim.weight"), "pound": ("pound", "dim.weight"), "pounds": ("pound", "dim.weight"),
    "lb": ("pound", "dim.weight"), "lbs": ("pound", "dim.weight"), "gram": ("gram", "dim.weight"), "grams": ("gram", "dim.weight"),
    "degree": ("degree", None), "degrees": ("degree", None), "dollar": ("dollar", "dim.price"), "dollars": ("dollar", "dim.price"),
    "euro": ("euro", "dim.price"), "euros": ("euro", "dim.price"), "percent": ("percent", None), "%": ("percent", None),
}
# unit-conversion to a canonical base unit per dimension (used when comparing numeric values)
UNIT_TO_BASE = {
    "year": 1.0, "month": 1 / 12, "week": 1 / 52.1775, "day": 1 / 365.25,
    "meter": 1.0, "centimeter": 0.01, "kilometer": 1000.0, "mile": 1609.344, "foot": 0.3048, "inch": 0.0254,
    "kilogram": 1.0, "gram": 0.001, "pound": 0.45359237, "dollar": 1.0, "euro": 1.0,
}

# ------------------------------------------------------------------------------------
# Names and kinship (used for gender / animacy features of unfamiliar mentions)
# ------------------------------------------------------------------------------------
MALE_NAMES = {n.lower() for n in """
John Michael David James Robert William Richard Thomas Charles Daniel Matthew Anthony Mark Paul Steven Andrew Kenneth
Joshua Kevin Brian George Edward Ronald Timothy Jason Jeffrey Ryan Jacob Gary Nicholas Eric Jonathan Stephen Larry
Justin Scott Brandon Benjamin Samuel Frank Gregory Raymond Alexander Patrick Jack Dennis Jerry Tyler Aaron Peter Henry
Adam Nathan Douglas Zachary Kyle Walter Harold Carl Arthur Albert Joe Juan Bruce Roger Philip Jose Ali Omar Hassan
Mohamed Muhammad Ahmed Kofi Kwame Juma Otieno Kamau Brian Tom Tim Sam Ben Alex Max Leo Liam Noah Oliver Ethan Mason
Logan Lucas Jake Peter Victor Hugo Felix Oscar Ivan Carlos Luis Miguel Pedro Raj Amit Ravi Chen Wei Hiro Kenji Yusuf
Ibrahim Abdul Said Tariq Brian Dan Don Ed Ted Bill Bob Rob Jim Joe Mike Nick Rick Steve Tony Andy Chris Greg Ken Ron
""".split()}
FEMALE_NAMES = {n.lower() for n in """
Mary Patricia Jennifer Linda Elizabeth Barbara Susan Jessica Sarah Karen Nancy Lisa Betty Margaret Sandra Ashley Kimberly
Emily Donna Michelle Dorothy Carol Amanda Melissa Deborah Stephanie Rebecca Sharon Laura Cynthia Kathleen Amy Angela
Shirley Anna Brenda Pamela Emma Nicole Helen Samantha Katherine Christine Debra Rachel Carolyn Janet Catherine Maria
Heather Diane Ruth Julie Olivia Joyce Virginia Victoria Kelly Lauren Christina Joan Evelyn Judith Megan Andrea Cheryl
Hannah Jacqueline Martha Gloria Teresa Ann Sara Madison Frances Kathryn Janice Jean Abigail Alice Julia Judy Sophia
Grace Denise Amber Doris Marilyn Danielle Beverly Isabella Theresa Diana Natalie Brittany Charlotte Marie Kayla
Alexis Lori Fatima Aisha Amina Zainab Wanjiru Akinyi Njeri Chloe Mia Ava Lily Zoe Ella Nora Ivy Eva Lena Mona Rose
Priya Anita Sunita Mei Yuki Sakura Layla Leila Noor Salma Amara Ada Eve Kate Kim Liz Beth Jane Sue Meg Jen Jenny Sally
""".split()}
MALE_KIN = {"father", "dad", "daddy", "brother", "son", "husband", "uncle", "grandfather", "grandpa", "boy", "man", "boyfriend",
            "gentleman", "king", "prince", "nephew", "waiter", "actor", "policeman", "fireman", "boss_m"}
FEMALE_KIN = {"mother", "mom", "mum", "mommy", "sister", "daughter", "wife", "aunt", "grandmother", "grandma", "girl", "woman",
              "girlfriend", "lady", "queen", "princess", "niece", "waitress", "actress"}
PERSON_NOUNS = {"person", "teacher", "student", "doctor", "nurse", "friend", "child", "kid", "baby", "people", "man", "woman",
                "boy", "girl", "neighbor", "customer", "engineer", "manager", "player", "driver", "worker", "colleague",
                "parent", "parents", "human", "humans", "men", "women", "children", "scientist", "artist", "writer",
                "author", "lawyer", "chef", "farmer", "pilot", "soldier", "citizen", "user", "owner", "guest", "stranger"}
ANIMAL_NOUNS = {"dog", "cat", "bird", "fish", "horse", "cow", "pig", "sheep", "chicken", "duck", "lion", "tiger", "bear", "wolf",
                "fox", "rabbit", "mouse", "elephant", "monkey", "snake", "frog", "animal", "animals", "mammal", "reptile",
                "insect", "puppy", "kitten", "whale", "dolphin", "eagle", "owl", "bee", "ant", "spider", "penguin", "swan",
                "dogs", "cats", "birds", "fishes", "horses", "cows", "pigs", "lions", "tigers", "bears", "wolves", "swans"}
PLACE_NOUNS = {"school", "city", "country", "town", "village", "park", "house", "home", "office", "store", "shop", "market",
               "hospital", "library", "restaurant", "airport", "station", "street", "room", "kitchen", "garden", "beach",
               "mountain", "river", "lake", "sea", "ocean", "island", "continent", "capital", "church", "bank", "hotel",
               "museum", "university", "college", "campus", "building", "farm", "forest", "desert", "world", "gym"}
ABSTRACT_NOUNS = {"idea", "time", "love", "freedom", "problem", "question", "answer", "reason", "plan", "goal", "task", "project",
                  "report", "story", "news", "information", "knowledge", "language", "music", "science", "history", "life",
                  "death", "peace", "war", "money", "price", "number", "name", "age", "height", "weight", "speed", "result"}
RELATIONAL_NOUNS = {"capital", "president", "king", "queen", "mother", "father", "brother", "sister", "owner", "author", "name",
                    "age", "height", "weight", "color", "colour", "size", "price", "population", "language", "currency",
                    "leader", "head", "founder", "creator", "inventor", "birthday", "address", "job", "hobby", "friend",
                    "wife", "husband", "son", "daughter", "boss", "teacher", "pet", "dog", "cat", "car", "favorite"}
TITLES_M = {"mr", "mr.", "sir", "mister"}
TITLES_F = {"mrs", "mrs.", "ms", "ms.", "miss", "madam", "lady"}
TITLES_N = {"dr", "dr.", "prof", "prof.", "professor", "doctor"}

COMMON_NOUNS = {
    # words that must never be treated as proper nouns when sentence-initial, plus frequent nouns
    "book", "books", "table", "chair", "car", "bike", "ball", "pen", "pencil", "paper", "phone", "computer", "laptop", "game",
    "apple", "apples", "banana", "orange", "cake", "bread", "water", "tea", "coffee", "milk", "food", "dinner", "lunch",
    "breakfast", "door", "window", "box", "bag", "gift", "present", "letter", "message", "email", "ticket", "key", "money",
    "movie", "film", "song", "picture", "photo", "thing", "things", "day", "week", "month", "year", "morning", "evening", "night",
    "weekend", "class", "lesson", "homework", "exam", "test", "job", "work", "meeting", "party", "trip", "plan", "list", "option",
    "options", "choice", "choices", "answer", "question", "report", "essay", "article", "website", "app", "page", "file", "code",
    "color", "colour", "name", "number", "tree", "flower", "house", "garden", "city", "country", "street", "sofa", "bed", "lamp",
    "clock", "watch", "shirt", "shoes", "hat", "coat", "dress", "mat", "sun", "moon", "star", "rain", "snow", "wind", "fire",
    "sky", "earth", "problem", "solution", "idea", "project", "task", "goal", "step", "feature", "bug", "error", "issue",
    "version", "release", "system", "engine", "memory", "knowledge", "language", "word", "sentence", "text", "data", "model",
    "science", "music", "art", "history", "math", "mathematics", "physics", "chemistry", "biology", "english", "capital",
}
