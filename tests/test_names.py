import pytest

from owrap.utils.memory import names


@pytest.fixture
def docs(tmp_path, monkeypatch):
    def project(project_id, subs=()):
        directory = tmp_path / "projects" / project_id
        directory.mkdir(parents=True)
        entries = "".join(
            f"  {sub}:\n    kind: regular\n    file: {sub}.md\n    parent: main\n"
            for sub in subs
        )
        (directory / f"{project_id}.yaml").write_text(
            f"schema_version: 1\nkind: project\nid: {project_id}\n"
            f"title: {project_id}\nmain: main.md\nrepositories: []\n"
            f"subprojects:{chr(10) + entries if entries else ' {}' + chr(10)}"
        )

    project("gen", ["wcp"])
    project("wcp")
    project("util", ["hpc-sync"])
    monkeypatch.setattr(names, "docs_root", lambda workspace="": tmp_path)


def test_bare_name_resolves_to_a_project_or_a_unique_subproject(docs):
    assert names.find_target("", "util") == ("util", "")
    assert names.find_target("", "hpc-sync") == ("util", "hpc-sync")


def test_ambiguous_name_lists_the_qualified_forms(docs):
    with pytest.raises(ValueError) as error:
        names.find_target("", "wcp")

    assert "wcp/main" in str(error.value)
    assert "gen/wcp" in str(error.value)


def test_qualified_forms_always_resolve(docs):
    assert names.find_target("", "gen/wcp") == ("gen", "wcp")
    assert names.find_target("", "wcp/main") == ("wcp", "")


def test_retired_words_are_refused(docs):
    with pytest.raises(ValueError, match="retired"):
        names.find_target("", "sub")


def test_new_names_must_be_unique_and_not_reserved(docs):
    names.check_new_name("", "fresh", "project")
    with pytest.raises(ValueError, match="reserved"):
        names.check_new_name("", "get", "project")
    with pytest.raises(ValueError, match="unique"):
        names.check_new_name("", "hpc-sync", "subproject")
