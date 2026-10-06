"""MongoDB collections for the database detector: Mongoose models and driver calls.

Only files that import mongoose or mongodb count (Firestore's v8 API also has
`db.collection("x")`, and a comment mentioning MongoDB proves nothing). A Mongoose model owns its
collection: the explicit third argument, else a lone schema's `{ collection: "x" }` option, else
the name Mongoose itself derives (`pluralize` below, ported from Mongoose 8.18
`lib/helpers/pluralize.js`, MIT, by TJ Holowaychuk). Driver `.collection("x")` calls use one.
Models are matched across line breaks (Prettier splits `mongoose.model<IUser>(...)` calls).
"""

import bisect
import re
from collections.abc import Callable

from cairn.model.graph import Fact

_IMPORT = re.compile(
    r"""(?:\bfrom\s+['"](?:mongoose|mongodb)['"]|\brequire\(\s*['"](?:mongoose|mongodb)['"]\s*\))"""
)
_NAME = r"""['"`]([A-Za-z_][\w.-]{0,99})['"`]"""
_GENERICS = r"(?:<(?:[^<>\n]|<[^<>\n]{0,100}>){0,200}>)?"
_MODEL = re.compile(
    rf"""\b(?:mongoose\.)?model{_GENERICS}\(\s*{_NAME}\s*,\s*[\w.]{{1,100}}\s*(?:,\s*{_NAME})?"""
)
_SCHEMA_COLLECTION = re.compile(rf"""\bcollection\s*:\s*{_NAME}""")
_COLLECTION = re.compile(rf"""\.(?:collection|getCollection)\(\s*{_NAME}\s*\)""")

# Mongoose's rules, in its order: the first that matches wins.
_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, flags), replacement)
    for pattern, replacement, flags in (
        (r"human$", "humans", re.I),
        (r"(m)an$", r"\1en", re.I),
        (r"(pe)rson$", r"\1ople", re.I),
        (r"(child)$", r"\1ren", re.I),
        (r"^(ox)$", r"\1en", re.I),
        (r"(ax|test)is$", r"\1es", re.I),
        (r"(octop|vir)us$", r"\1i", re.I),
        (r"(alias|status)$", r"\1es", re.I),
        (r"(bu)s$", r"\1ses", re.I),
        (r"(buffal|tomat|potat)o$", r"\1oes", re.I),
        (r"([ti])um$", r"\1a", re.I),
        (r"sis$", "ses", re.I),
        (r"(?:([^f])fe|([lr])f)$", r"\1\2ves", re.I),
        (r"(hive)$", r"\1s", re.I),
        (r"([^aeiouy]|qu)y$", r"\1ies", re.I),
        (r"(x|ch|ss|sh)$", r"\1es", re.I),
        (r"(matr|vert|ind)ix|ex$", r"\1ices", re.I),
        (r"([m|l])ouse$", r"\1ice", re.I),
        (r"(kn|w|l)ife$", r"\1ives", re.I),
        (r"(quiz)$", r"\1zes", re.I),
        (r"^goose$", "geese", re.I),
        (r"s$", "s", re.I),
        (r"([^a-z])$", r"\1", 0),
        (r"$", "s", re.I),
    )
)
_UNCOUNTABLES = frozenset(
    {
        "advice",
        "energy",
        "excretion",
        "digestion",
        "cooperation",
        "health",
        "justice",
        "labour",
        "machinery",
        "equipment",
        "information",
        "pollution",
        "sewage",
        "paper",
        "money",
        "species",
        "series",
        "rain",
        "rice",
        "fish",
        "sheep",
        "moose",
        "deer",
        "news",
        "expertise",
        "status",
        "media",
    }
)


def mongoose_collection(model: str) -> str:
    """The collection Mongoose stores `model` in by default: "User" -> users, "Quiz" -> quizzes."""
    name = model.lower()
    if name in _UNCOUNTABLES:
        return name
    for pattern, replacement in _RULES:
        if pattern.search(name):
            return pattern.sub(replacement, name)
    return name


def uses_mongo(text: str) -> bool:
    return _IMPORT.search(text) is not None


Make = Callable[[int, str], Fact]  # (line number, collection) -> a table fact


def mongo_tables(text: str, make: Make) -> tuple[list[Fact], list[Fact]]:
    """(owned collections, used collections) of a file that imports mongoose or mongodb."""
    starts = [0, *(i + 1 for i, ch in enumerate(text) if ch == "\n")]
    models = list(_MODEL.finditer(text))
    options = [m.group(1) for m in _SCHEMA_COLLECTION.finditer(text)]
    # A `{ collection: "x" }` option can be paired with a model only when the file has one each.
    lone_option = options[0] if len(options) == 1 and len(models) == 1 else None
    owned = [
        make(
            bisect.bisect_right(starts, m.start(1)),
            m.group(2) or lone_option or mongoose_collection(m.group(1)),
        )
        for m in models
    ]
    used = [
        make(bisect.bisect_right(starts, m.start(1)), m.group(1))
        for m in _COLLECTION.finditer(text)
    ]
    return owned, used
