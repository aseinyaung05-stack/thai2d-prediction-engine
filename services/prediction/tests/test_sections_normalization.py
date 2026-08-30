"""Section classification + 2D normalization (engine-side mirror of shared)."""
import numpy as np
import pytest

from prediction.features.builder import N_NUMBERS, SECTION_BOUNDS, classify_section, section_of_array


def test_section_boundaries():
    assert classify_section(0) == "A"
    assert classify_section(24) == "A"
    assert classify_section(25) == "B"
    assert classify_section(49) == "B"
    assert classify_section(50) == "C"
    assert classify_section(74) == "C"
    assert classify_section(75) == "D"
    assert classify_section(99) == "D"


def test_out_of_range_rejected():
    with pytest.raises(ValueError):
        classify_section(100)
    with pytest.raises(ValueError):
        classify_section(-1)


def test_each_section_has_25_numbers():
    for lo, hi in SECTION_BOUNDS.values():
        assert hi - lo + 1 == 25
    total = sum(hi - lo + 1 for lo, hi in SECTION_BOUNDS.values())
    assert total == N_NUMBERS


def test_vectorized_sections_match_scalar():
    arr = np.arange(100)
    vec = section_of_array(arr)
    for n in range(100):
        assert vec[n] == classify_section(n)
