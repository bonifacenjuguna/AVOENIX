import pytest

from intelligence.engines.emotion.engine import EmotionEngine
from intelligence.engines.input.engine import InputProcessingEngine
from intelligence.engines.language.engine import LanguageEngine

_ie, _le, E = InputProcessingEngine(), LanguageEngine(), EmotionEngine()


def sig(text):
    return E.analyze(_le.analyze(_ie.process(text)))


@pytest.mark.parametrize("text,label", [
    ("I am so happy today!", "positive"), ("This is awful and I hate it", "negative"), ("What is the capital of France?", "neutral"),
    ("I'm not happy about this", "negative"), ("It's not bad", "positive"), ("thanks a lot, this is great 😊", "positive"),
    ("I am very angry!!!", "negative"), ("The service was good but the food was terrible", "negative"),
    ("The food was terrible but the service was good", "positive"),
])
def test_label(text, label):
    assert sig(text).label == label


def test_negation_flips_and_intensity_scales():
    assert sig("I am happy").valence > 0 > sig("I am not happy").valence
    assert sig("I am extremely happy").valence >= sig("I am happy").valence
    assert sig("I am slightly sad").valence > sig("I am very sad").valence


def test_arousal_and_certainty():
    calm, loud = sig("I am sad"), sig("I AM SO ANGRY!!!")
    assert loud.arousal > calm.arousal and loud.flags["shouting"]
    n = sig("The table is wooden")
    assert n.certainty == 0.0 and n.cues == ["no affect cues"]
    assert sig("I am sad and angry and scared").certainty > sig("I am sad").certainty


def test_mixed_and_emoji():
    assert sig("I love the idea but I am so worried 😢").label in ("mixed", "negative")
    assert sig("ok 😡").valence < 0
    assert sig("ok 🎉").emotions[0]["name"] == "joy"
