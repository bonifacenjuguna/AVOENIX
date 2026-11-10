from fractions import Fraction

import pytest

from intelligence.algorithms import arithmetic as ar
from intelligence.algorithms.confidence import band, chain, laplace, noisy_or, weighted_geometric
from intelligence.algorithms.constraint import CSP, rankings
from intelligence.algorithms.partial_order import PartialOrder
from intelligence.algorithms.text_similarity import BM25, fuzzy_match, jaro_winkler, levenshtein, words


def test_partial_order_transitivity_and_extrema():
    po = PartialOrder()
    po.add_greater("John", "Peter")
    po.add_greater("Peter", "David")
    assert po.compare("John", "David") == ">"
    assert po.compare("David", "John") == "<"
    assert po.unique_minimum() == "David" and po.unique_maximum() == "John"
    assert po.chain("John", "David") == ["John", "Peter", "David"]
    assert po.topological_ranking() == [["John"], ["Peter"], ["David"]]


def test_partial_order_undetermined_minimum():
    po = PartialOrder()
    po.add_greater("A", "C")
    po.add_greater("B", "C")
    po.add_greater("A", "D")
    assert po.unique_minimum() is None
    assert set(po.minimal()) == {"C", "D"}
    assert po.compare("C", "D") == "?"


def test_partial_order_cycle_and_equality():
    po = PartialOrder()
    po.add_greater("A", "B"); po.add_greater("B", "C"); po.add_greater("C", "A")
    assert po.find_cycle() and not po.is_consistent()
    eq = PartialOrder()
    eq.add_equal("A", "B"); eq.add_greater("B", "C")
    assert eq.compare("A", "C") == ">" and eq.compare("A", "B") == "="


def test_not_greater_violation():
    po = PartialOrder()
    po.add_greater("A", "B"); po.add_not_greater("A", "B")
    assert not po.is_consistent() and po.violations()


def test_csp_enumerates_exactly_the_consistent_rankings():
    sols = rankings(["A", "B", "C"], greater=[("A", "B"), ("B", "C")])
    assert len(sols) == 1 and sols[0]["A"] > sols[0]["B"] > sols[0]["C"]
    # only A>C known: B can be anywhere -> several weak orders
    sols = rankings(["A", "B", "C"], greater=[("A", "C")])
    assert len(sols) > 1
    # contradictory
    assert rankings(["A", "B"], greater=[("A", "B"), ("B", "A")]) == []


def test_csp_generic_solver():
    csp = CSP()
    for v in "xyz":
        csp.add_variable(v, [1, 2, 3])
    csp.add_constraint(("x", "y"), lambda a, b: a != b)
    csp.add_constraint(("y", "z"), lambda a, b: a < b)
    sols = list(csp.solutions())
    assert sols and all(s["x"] != s["y"] and s["y"] < s["z"] for s in sols)
    assert csp.count_solutions() == len(sols)


def test_arithmetic_exact_and_safe():
    assert ar.evaluate(("add", 2, ("mul", 3, 4))) == 14
    assert ar.evaluate(("div", 1, 3)) == Fraction(1, 3)
    assert ar.evaluate(("add", 0.1, 0.2)) == Fraction(3, 10)        # decimal-faithful
    assert ar.render(Fraction(7, 2)) == "3.5"
    assert ar.render(Fraction(1, 3)).startswith("1/3")
    assert ar.evaluate(("percent_of", 20, 150)) == 30
    assert ar.evaluate(("sqrt", 144)) == 12
    with pytest.raises(ar.ArithmeticError_):
        ar.evaluate(("div", 1, 0))
    with pytest.raises(ar.ArithmeticError_):
        ar.evaluate(("pow", 10, 1000))
    with pytest.raises(ar.ArithmeticError_):
        ar.evaluate("__import__('os').system('x')")


def test_confidence_semantics():
    assert noisy_or([0.5, 0.5]) == pytest.approx(0.75)
    assert chain([0.9, 0.9]) == pytest.approx(0.81)
    assert weighted_geometric({"a": 1.0, "b": 0.1}, {"a": 1, "b": 1}) < 0.4   # weak part drags down
    assert laplace(3, 3) == pytest.approx(0.8)
    assert band(None) == "not_evaluated" and band(0.9) == "high" and band(0.2) == "low"


def test_text_similarity():
    assert levenshtein("kitten", "sitting") == 3
    assert jaro_winkler("martha", "marhta") > 0.95
    assert fuzzy_match("Catherine", "Katherine") > fuzzy_match("Catherine", "Michael")
    bm = BM25([words("the cat sat on the mat"), words("dogs chase cats"), words("my favorite colour is green")])
    scores = bm.scores(words("what is my favorite colour"))
    assert scores.index(max(scores)) == 2
