import cairn


def test_version_is_semver() -> None:
    parts = cairn.__version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)
