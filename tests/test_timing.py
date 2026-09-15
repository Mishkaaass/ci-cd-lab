import opsboard.timing as timing


def test_monotonic_milliseconds_converts_nanoseconds_to_milliseconds(
    monkeypatch,
):
    monkeypatch.setattr(
        timing.time,
        "monotonic_ns",
        lambda: 2_345_678_901,
    )

    assert timing.monotonic_milliseconds() == 2345
