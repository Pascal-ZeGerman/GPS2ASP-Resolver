"""Spike 013: refusal diagnostics label where a fix sits relative to the lane band."""

from gps2asp.resolver import _classify_band


def test_within_lane_is_lane_ambig():
    assert _classify_band(5.0, 9.7) == "lane_ambig"
    assert _classify_band(9.7, 9.7) == "lane_ambig"


def test_up_to_15ft_past_lane_is_past_lane():
    assert _classify_band(16.0, 9.7) == "past_lane"
    assert _classify_band(24.7, 9.7) == "past_lane"


def test_beyond_that_is_far():
    assert _classify_band(30.0, 9.7) == "far"
