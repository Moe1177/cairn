"""Maven and Gradle: a JVM library links to the repos that build against it."""

from pathlib import Path

from cairn.bench.workspace import materialize
from cairn.detectors import jvm
from cairn.match.matcher import RepoFacts, match_edges
from cairn.model.graph import Contracts
from cairn.scan import scan_workspace

POM = """<?xml version="1.0"?>
<project>
  <!-- <groupId>com.example.commented</groupId> -->
  <parent>
    <groupId>com.acme</groupId>
    <artifactId>acme-parent</artifactId>
    <version>1</version>
  </parent>
  <artifactId>orders-client</artifactId>
  <dependencyManagement>
    <dependencies>
      <dependency><groupId>com.acme</groupId><artifactId>pinned-only</artifactId></dependency>
    </dependencies>
  </dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>com.acme</groupId>
      <artifactId>money</artifactId>
      <version>2.1</version>
    </dependency>
    <dependency><groupId>${project.groupId}</groupId><artifactId>self-ref</artifactId></dependency>
    <dependency><groupId>junit</groupId><artifactId>junit</artifactId></dependency>
  </dependencies>
</project>
"""


def test_a_pom_publishes_its_coordinate_and_uses_its_dependencies() -> None:
    published, depends = jvm.maven(POM)
    assert published == "maven:com.acme:orders-client"  # group from the parent
    assert depends == ["maven:com.acme:money", "maven:junit:junit"]


def test_a_pom_is_never_parsed_as_xml() -> None:
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE p [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
        "<project><groupId>&b;</groupId><artifactId>x</artifactId></project>"
    )
    assert jvm.maven(bomb) == (None, [])


GRADLE = """
plugins { id 'java-library' }
dependencies {
    implementation 'com.openfaas:model:0.1.1'
    api("com.acme:money:2.1")
    testImplementation 'junit:junit:4.12'
    implementation libs.guava
    implementation project(':core')
}
publishing { publications { maven(MavenPublication) {
    artifactId = 'entrypoint'
} } }
"""


def test_a_gradle_build_publishes_and_depends() -> None:
    published, depends = jvm.gradle(
        GRADLE + "group = 'com.openfaas'\n", folder="lib", settings=None, inherited_group=None
    )
    assert published == "maven:com.openfaas:entrypoint"
    assert depends == ["maven:com.openfaas:model", "maven:com.acme:money", "maven:junit:junit"]


def test_a_gradle_artifact_falls_back_to_the_settings_name_then_the_folder() -> None:
    build = "buildscript {\n    group = 'com.openfaas'\n}\n"
    named = jvm.gradle(
        build, folder="java11", settings="rootProject.name = 'model'", inherited_group=None
    )
    assert named[0] == "maven:com.openfaas:model"
    plain = jvm.gradle("", folder="core", settings=None, inherited_group="com.acme")
    assert plain[0] == "maven:com.acme:core"
    assert jvm.gradle("", folder="core", settings=None, inherited_group=None)[0] is None


def _workspace(tmp_path: Path, repos: dict[str, dict[str, str]]) -> Path:
    tree = tmp_path / "tree"
    for repo, files in repos.items():
        for rel, text in {**files, ".fixture-repo": ""}.items():
            (tree / repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (tree / repo / rel).write_text(text, encoding="utf-8")
    return materialize(tree, tmp_path / "ws").resolve()


def test_a_jvm_library_links_to_the_repos_that_build_against_it(tmp_path: Path) -> None:
    ws = _workspace(
        tmp_path,
        {
            "sdk": {
                "java/model/build.gradle": "buildscript { group = 'com.openfaas' }\n",
                "java/model/settings.gradle": "rootProject.name = 'model'\n",
                "build.gradle": "allprojects { group = 'com.openfaas' }\n",
                "java/entrypoint/build.gradle": "dependencies { api 'org.slf4j:slf4j-api:2' }\n",
            },
            "templates": {
                "template/java17/function/build.gradle": GRADLE,
            },
            "billing": {"pom.xml": POM.replace("orders-client", "billing")},
        },
    )
    workspace = scan_workspace(ws).workspace
    sdk = next(r for r in workspace.repos if r.id == "sdk")
    published = {f.value for f in sdk.contracts.exposes if f.value.startswith("maven:")}
    assert published == {
        "maven:com.openfaas:model",
        "maven:com.openfaas:entrypoint",
        "maven:com.openfaas:sdk",
    }
    links = {(e.source, e.target, e.type.value) for e in workspace.edges}
    assert ("templates", "sdk", "depends_on_package") in links
    assert not any("billing" in (s, t) for s, t, _ in links)  # money and junit: nobody here


def test_two_repos_publishing_one_coordinate_make_an_ambiguous_link() -> None:
    from cairn.model.graph import Fact, FactKind

    def repo(id_: str, exposes=(), consumes=()) -> RepoFacts:
        facts = lambda vs: tuple(Fact(kind=FactKind.PACKAGE, value=v) for v in vs)  # noqa: E731
        return RepoFacts(
            id=id_, path=id_, contracts=Contracts(exposes=facts(exposes), consumes=facts(consumes))
        )

    edges = match_edges(
        [
            repo("a", exposes=["maven:com.acme:money"]),
            repo("b", exposes=["maven:com.acme:money"]),
            repo("c", consumes=["maven:com.acme:money"]),
        ]
    )
    used = {(e.source, e.target, e.confidence.value) for e in edges if e.source == "c"}
    assert used == {
        ("c", "a", "ambiguous"),
        ("c", "b", "ambiguous"),
    }
