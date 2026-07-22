"""P1 regression tests — place-name extraction tail-stops.

The original bug: `_extract_place_name` captured ``"goa around the"`` for
queries like "near Goa around the last monsoon" because the place-spatial
regex's tail-stop alternation included ``during`` and relative-season tokens
but NOT the proximity prepositions ``around``/``off``/``by`` or the
standalone article ``the``. The non-greedy capture then ate ``"around the"``
before the relative-season stop (`` last monsoon``) fired. The gazetteer
failed on ``"goa around the"``, which cascaded into LLM recovery and wrong
results (the query-7 failure in production logs).

Fix: added ``around|off|by`` and standalone ``the`` as tail-stops in
``_PLACE_SPATIAL_RE``, plus a strip-from-first-stopword cleanup that also
covers the generic-regex path.
"""
import pytest

from floatchat.intent_parser.regex import RegexIntentParser


@pytest.fixture(scope="module")
def parser():
    return RegexIntentParser()


# --------------------------------------------------------------------------- #
# The four required cases from the P1 spec
# --------------------------------------------------------------------------- #
def test_place_near_around_the_last_monsoon(parser):
    # The headline bug: previously returned "goa around the"
    assert parser._extract_place_name("near goa around the last monsoon") == "goa"


def test_place_near_last_summer(parser):
    assert parser._extract_place_name("near goa last summer") == "goa"


def test_place_near_during_monsoon(parser):
    assert parser._extract_place_name("near mumbai during monsoon") == "mumbai"


def test_place_off_the_kerala_coast(parser):
    # Multi-word place must survive — article "the" is consumed by the prefix.
    assert parser._extract_place_name("off the kerala coast") == "kerala coast"


# --------------------------------------------------------------------------- #
# The original failing query (query 7) and close variants
# --------------------------------------------------------------------------- #
def test_place_query7_full(parser):
    # Full production query that broke in logs (intent #7)
    got = parser._extract_place_name(
        "show me floats that were alive near goa around the last monsoon"
    )
    assert got == "goa"


def test_place_off_preposition_stops_capture(parser):
    assert parser._extract_place_name("floats near goa off the coast") == "goa"


def test_place_by_preposition_stops_capture(parser):
    assert parser._extract_place_name("floats near goa by the coast") == "goa"


# --------------------------------------------------------------------------- #
# Regression guards: legitimate multi-word places are preserved
# --------------------------------------------------------------------------- #
def test_place_sri_lanka_preserved(parser):
    assert parser._extract_place_name("floats near sri lanka") == "sri lanka"


def test_place_andaman_preserved(parser):
    # "and" mid-name must not be stripped (only trailing stop-words are)
    assert parser._extract_place_name("floats near andaman and nicobar") == "andaman and nicobar"


def test_place_bare_no_tail(parser):
    assert parser._extract_place_name("floats near goa") == "goa"


# --------------------------------------------------------------------------- #
# End-to-end: the place resolves to coordinates via the gazetteer, and the
# intent routes to radius_search (not "unknown").
# --------------------------------------------------------------------------- #
def test_query7_parses_to_radius_search_with_coords(parser):
    parsed = parser.parse("floats near goa around the last monsoon")
    assert parsed.intent == "radius_search"
    assert parsed.lat is not None and parsed.lon is not None
    # Goa is ~15.3 N, 73.9 E — sanity check the gazetteer resolved something
    # in the right hemisphere (India region).
    assert 5.0 < parsed.lat < 25.0
    assert 70.0 < parsed.lon < 90.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
