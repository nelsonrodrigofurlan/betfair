from palpitaria.services.scouting_preferences import domain_from_url
from palpitaria.services.skills_reader import list_skill_docs, read_skill_doc


def test_domain_from_url():
    assert domain_from_url("https://www.example.com/path") == "example.com"
    assert domain_from_url("ge.globo.com/futebol") == "ge.globo.com"


def test_read_skill_doc_rejects_traversal():
    assert read_skill_doc("../main.py") is None
    assert read_skill_doc("betfair/../../etc/passwd") is None


def test_list_skill_docs_includes_betfair_skill():
    docs = list_skill_docs()
    paths = {d.rel_path for d in docs}
    assert "betfair/SKILL.md" in paths
