from handoff.source_tags import resolve_source_tags

FILES = ["app/(tabs)/settings/devices.tsx", "providers/AuthProvider.tsx"]


def test_path_with_parentheses_resolves_to_its_number() -> None:
    text = "x [app/(tabs)/settings/devices.tsx][providers/AuthProvider.tsx]"
    assert resolve_source_tags(text, FILES) == ("x [1][2]", [])


def test_markdown_link_is_left_untouched() -> None:
    text = "see [docs.md](http://b.c) and [a](app/(tabs)/x.tsx)"
    assert resolve_source_tags(text, FILES) == (text, [])


def test_bare_numeric_tag_is_still_dropped() -> None:
    assert resolve_source_tags("x [1]", FILES) == ("x", ["1"])


def test_unknown_path_with_parentheses_is_dropped_and_reported() -> None:
    text = "x [app/(auth)/login.tsx]"
    assert resolve_source_tags(text, FILES) == ("x", ["app/(auth)/login.tsx"])
