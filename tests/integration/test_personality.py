import pytest

from intelligence.core.types import Scope
from intelligence.engines.emotion.engine import EmotionEngine
from intelligence.engines.input.engine import InputProcessingEngine
from intelligence.engines.language.engine import LanguageEngine
from intelligence.engines.memory.engine import MemoryEngine
from intelligence.engines.personality.engine import PersonalityEngine
from intelligence.storage import MemoryBackend

A, B = Scope("p1", "alice"), Scope("p1", "bob")
_ie, _le, _ee = InputProcessingEngine(), LanguageEngine(), EmotionEngine()


@pytest.fixture()
def pe():
    return PersonalityEngine(MemoryEngine(MemoryBackend()))


def lr(t):
    return _le.analyze(_ie.process(t))


def test_base_profile_without_history(pe):
    p = pe.profile(A)
    assert p.emoji_allowed and 0 < p.emoji_level < 0.5 and p.reasons == []


def test_observed_style_adapts_per_user_and_stays_isolated(pe):
    for t in ["hey lol whats up 😂", "yo gonna ask something 😂", "haha cool 😂"]:
        pe.observe(A, lr(t))
    for t in ["Could you please explain the process?", "Thank you, I would appreciate more detail."]:
        pe.observe(B, lr(t))
    a, b = pe.profile(A), pe.profile(B)
    assert a.formality < b.formality and a.emoji_level > b.emoji_level
    assert "😂" in a.recent_user_emoji and b.recent_user_emoji == []
    assert pe.memory.inspect(A)["total_rows"] == 1                      # updated in place, no row growth


def test_explicit_preferences_override_observation(pe):
    for _ in range(3):
        pe.observe(A, lr("hey 😂 lol"))
    pe.memory.set_preference(A, "style.emoji", "none")
    pe.memory.set_preference(A, "style.formality", "formal")
    p = pe.profile(A)
    assert not p.emoji_allowed and p.emoji_level == 0 and p.formality > 0.8
    assert any("no emoji" in r for r in p.reasons)


def test_distress_suppresses_emoji_and_initiative(pe):
    pe.memory.set_preference(A, "style.emoji", "more")
    e = _ee.analyze(lr("I am so scared and hopeless!!!"))
    p = pe.profile(A, e)
    assert p.emoji_level == 0 and p.initiative == 0 and any("upset" in r for r in p.reasons)
