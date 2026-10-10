"""Maven and Gradle builds: the coordinate (`group:artifact`) a build publishes, and the ones it
depends on, so a JVM library links to the repos that use it the way an npm package does.

Builds are read with patterns, never an XML parser or Gradle itself: a pom.xml from an untrusted
repo can't expand entities, and nothing is evaluated. Only literal coordinates count; a
`${project.groupId}` or a version catalog alias names nothing comparable.
"""

import re
from pathlib import PurePosixPath

GRADLE_BUILDS = ("build.gradle", "build.gradle.kts")
GRADLE_SETTINGS = ("settings.gradle", "settings.gradle.kts")
MAVEN_BUILD = "pom.xml"
_ID = r"[A-Za-z0-9_][\w.-]{0,199}"
# A statement starts a line or follows `{` or `;`: `buildscript { group = 'com.acme' }`.
_START = r"(?:^|[{;])\s*"
_GROUP = re.compile(rf"""{_START}(?:project\.)?group\s*=\s*["']({_ID})["']""", re.M)
_ARTIFACT = re.compile(rf"""{_START}artifactId\s*=\s*["']({_ID})["']""", re.M)
_ROOT_NAME = re.compile(rf"""rootProject\.name\s*=\s*["']({_ID})["']""")
_CONFIGURATIONS = (
    "implementation|api|compile|compileOnly|runtimeOnly|runtime|testImplementation|testCompile"
    "|testRuntimeOnly|testCompileOnly|annotationProcessor|kapt|ksp"
)
_GRADLE_DEP = re.compile(
    rf"""{_START}(?:{_CONFIGURATIONS})\s*\(?\s*(?:platform\(\s*)?["']({_ID}):({_ID})(?::[^"'\s]*)?["']""",
    re.M,
)
_XML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_SKIPPED_BLOCKS = re.compile(
    r"<(parent|dependencyManagement|dependencies|build|profiles|reporting|pluginRepositories"
    r"|repositories|distributionManagement)\b[^>]*>.*?</\1>",
    re.S,
)
_PARENT = re.compile(r"<parent\b[^>]*>(.*?)</parent>", re.S)
_DEPENDENCY_MANAGEMENT = re.compile(
    r"<dependencyManagement\b[^>]*>.*?</dependencyManagement>", re.S
)
_DEPENDENCIES = re.compile(r"<dependencies\b[^>]*>(.*?)</dependencies>", re.S)
_DEPENDENCY = re.compile(r"<dependency\b[^>]*>(.*?)</dependency>", re.S)
_TAG = {name: re.compile(rf"<{name}>\s*({_ID})\s*</{name}>") for name in ("groupId", "artifactId")}


def coordinate(group: str, artifact: str) -> str:
    return f"maven:{group}:{artifact}"


def maven(text: str) -> tuple[str | None, list[str]]:
    """A pom's own coordinate (its group may come from its parent) and its dependencies."""
    text = _XML_COMMENT.sub("", text)
    own = _SKIPPED_BLOCKS.sub("", text)
    parent = _PARENT.search(text)
    group = _tag(own, "groupId") or (_tag(parent.group(1), "groupId") if parent else None)
    artifact = _tag(own, "artifactId")
    published = coordinate(group, artifact) if group and artifact else None
    used = _DEPENDENCY_MANAGEMENT.sub("", text)  # versions pinned there, not dependencies
    depends = [
        coordinate(g, a)
        for block in _DEPENDENCIES.findall(used)
        for dep in _DEPENDENCY.findall(block)
        if (g := _tag(dep, "groupId")) and (a := _tag(dep, "artifactId"))
    ]
    return published, list(dict.fromkeys(depends))


def gradle_group(text: str) -> str | None:
    match = _GROUP.search(text)
    return match.group(1) if match else None


def gradle(
    text: str, *, folder: str, settings: str | None, inherited_group: str | None
) -> tuple[str | None, list[str]]:
    """A Gradle project's coordinate and dependencies. Its artifact is the publication's
    `artifactId`, else `rootProject.name` from settings beside it, else its folder's name; its
    group is its own `group = ...`, else one set by a build above it (`allprojects`)."""
    group = gradle_group(text) or inherited_group
    explicit = _ARTIFACT.search(text)
    root_name = _ROOT_NAME.search(settings) if settings else None
    artifact = (
        explicit.group(1)
        if explicit
        else root_name.group(1)
        if root_name
        else PurePosixPath(folder).name or None
    )
    published = coordinate(group, artifact) if group and artifact else None
    depends = [coordinate(g, a) for g, a in _GRADLE_DEP.findall(text)]
    return published, list(dict.fromkeys(depends))


def _tag(text: str, name: str) -> str | None:
    match = _TAG[name].search(text)
    return match.group(1) if match else None
