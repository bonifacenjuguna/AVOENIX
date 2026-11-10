"""Open-class supplements: non-gradable adjectives and ambiguous noun/verb words."""

ADJECTIVES = {
    "happy", "sad", "angry", "tired", "hungry", "thirsty", "ready", "sure", "afraid", "glad", "proud", "excited", "nervous",
    "worried", "upset", "sick", "busy", "free", "full", "empty", "alive", "dead", "true", "false", "right", "wrong", "same",
    "different", "other", "own", "main", "public", "private", "special", "important", "famous", "beautiful", "ugly", "nice",
    "kind", "friendly", "lovely", "wonderful", "terrible", "awful", "amazing", "great", "fine", "perfect", "necessary",
    "possible", "impossible", "available", "popular", "common", "local", "national", "international", "red", "blue", "green",
    "yellow", "black", "white", "brown", "pink", "purple", "gray", "grey", "mortal", "immortal", "human", "female", "male",
    "sweet", "sour", "bitter", "delicious", "dirty", "wet", "dry", "safe", "dangerous", "healthy", "funny", "boring",
    "interesting", "careful", "clear", "similar", "mad", "glad", "lonely", "calm", "anxious", "confused", "curious",
    "disappointed", "frustrated", "grateful", "thankful", "joyful", "cheerful", "miserable", "depressed", "scared", "terrified",
    "annoyed", "furious", "pleased", "satisfied", "bored", "embarrassed", "ashamed", "jealous", "relieved", "hopeful",
    "stressed", "overwhelmed", "exhausted", "sleepy", "awesome", "fantastic", "horrible", "brilliant", "excellent",
    "poor_", "useful", "useless", "helpful", "harmless", "harmful", "polite", "rude", "honest", "loyal", "brave", "shy",
    "lazy", "hardworking", "creative", "mammal", "wild", "domestic", "daily", "weekly", "monthly", "annual", "late", "early",
    "recent", "current", "former", "previous", "next", "last", "first", "second", "third", "final", "only", "whole", "entire",
    "certain", "likely", "unlikely", "ancient", "modern", "digital", "online", "offline", "physical", "mental", "social",
    "political", "economic", "natural", "artificial", "general", "specific", "single", "double", "multiple", "various",
    "enough", "several", "numerous", "pregnant", "married", "single_", "ill", "well", "fresh", "rare", "soft", "loud",
    "quiet", "bright", "dark", "heavy_", "thick", "thin", "round", "flat", "sharp", "smooth", "rough", "fair", "equal",
    "mine", "yours", "ours", "theirs", "alone", "asleep", "awake", "aware", "able", "unable", "present", "absent",
    "correct", "incorrect", "accurate", "inaccurate", "sorry", "welcome", "okay", "ok_", "worth", "due", "open_", "closed",
    "legal", "illegal", "real", "unreal", "ordinary", "normal", "strange", "weird", "odd", "obvious", "complete", "incomplete",
}
ADJECTIVES = {a for a in ADJECTIVES if not a.endswith("_")}

#: words that are both noun and verb (lemma form) - disambiguated by context
NOUN_VERB = {
    "book", "play", "plan", "help", "work", "need", "call", "test", "drink", "watch", "love", "light", "show", "cook", "open",
    "close", "use", "rain", "walk", "run", "talk", "answer", "start", "end", "visit", "study", "phone", "drive", "change", "turn",
    "look", "smile", "laugh", "cry", "fall", "win", "move", "wish", "hope", "fix", "clean", "mean", "name", "design", "draft",
    "review", "research", "deploy", "present", "offer", "stay", "wait", "sleep", "dream", "kiss", "hand", "address", "point",
    "park", "post", "save", "rest", "reach", "pick", "pass", "ride", "swim", "fish", "step", "joke", "cut", "hit", "set",
    "order", "record", "rule", "sign", "mark", "film", "paint", "cover", "count", "return", "report", "support", "train",
    "surprise", "promise", "reply", "request", "attack", "copy", "check", "email", "message", "text", "ban", "lead", "kick",
}
