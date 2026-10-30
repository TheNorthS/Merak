from pathlib import Path

import httpx
import pytest

from server.services.knowledge_sources import KnowledgeSourceService
from server.services.notification import (
    NotificationService,
    NotifyChannel,
)
from server.services.overleaf_sync import (
    OverleafProject,
    OverleafSync,
)
from server.workflows.engine import WorkflowEngine, WorkflowRun


class FakeHttpClient:
    def __init__(self, response, *args, **kwargs):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, *args, **kwargs):
        return self.response

    async def post(self, *args, **kwargs):
        return self.response


@pytest.mark.asyncio
async def test_zotero_returns_structured_metadata(monkeypatch):
    response = httpx.Response(
        200,
        json=[
            {
                "key": "ITEM123",
                "version": 4,
                "data": {
                    "itemType": "journalArticle",
                    "title": "A Reliable EEG Study",
                    "creators": [
                        {"firstName": "Ada", "lastName": "Lovelace"},
                        {"name": "Research Group"},
                    ],
                    "date": "2025",
                    "publicationTitle": "Journal of Tests",
                    "DOI": "10.1000/test",
                    "url": "https://example.test/paper",
                    "abstractNote": "Evidence-bearing abstract.",
                    "tags": [{"tag": "EEG"}, {"tag": "foundation model"}],
                },
            }
        ],
    )
    monkeypatch.setenv("ZOTERO_API_KEY", "secret")
    monkeypatch.setenv("ZOTERO_USER_ID", "12345")
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *args, **kwargs: FakeHttpClient(response),
    )

    records = await KnowledgeSourceService().search_zotero("EEG", limit=5)

    assert records == [
        {
            "item_key": "ITEM123",
            "version": 4,
            "item_type": "journalArticle",
            "title": "A Reliable EEG Study",
            "creators": ["Ada Lovelace", "Research Group"],
            "date": "2025",
            "publication": "Journal of Tests",
            "doi": "10.1000/test",
            "url": "https://example.test/paper",
            "abstract": "Evidence-bearing abstract.",
            "tags": ["EEG", "foundation model"],
        }
    ]


def test_obsidian_search_is_bounded_and_skips_hidden_content(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "visible.md").write_text(
        "# EEG Foundation Model\nA montage invariant method.\n",
        encoding="utf-8",
    )
    hidden = vault / ".obsidian"
    hidden.mkdir()
    (hidden / "private.md").write_text("EEG foundation model secret", encoding="utf-8")
    (vault / ".private.md").write_text("EEG foundation model hidden", encoding="utf-8")
    (vault / "oversized.md").write_text(
        "EEG foundation model " + ("x" * (2 * 1024 * 1024)),
        encoding="utf-8",
    )
    try:
        (vault / "outside-link.md").symlink_to(tmp_path / "outside.md")
    except OSError:
        pass

    records = KnowledgeSourceService().search_obsidian(
        "EEG foundation model",
        vault_path=str(vault),
        limit=10,
    )

    assert [record["path"] for record in records] == ["visible.md"]
    assert set(records[0]["matched_terms"]) == {"eeg", "foundation", "model"}
    assert records[0]["snippets"]


@pytest.mark.asyncio
async def test_knowledge_artifacts_are_injected_into_literature_prompt(tmp_path, monkeypatch):
    project = tmp_path / "project"
    (project / "literature").mkdir(parents=True)
    service = KnowledgeSourceService()

    async def fake_zotero(query, limit):
        return [{"title": "Library Paper", "doi": "10.1/library"}]

    monkeypatch.setattr(service, "search_zotero", fake_zotero)
    monkeypatch.setattr(
        service,
        "search_obsidian",
        lambda query, vault_path="", limit=15: [
            {"path": "idea.md", "snippets": ["Internal hypothesis"]}
        ],
    )

    results = await service.collect_for_project(
        str(project),
        "EEG robustness",
        zotero=True,
        obsidian=True,
        limit=10,
    )
    run = WorkflowRun(
        project_path=str(project),
        options={"enable_zotero": True, "enable_obsidian": True,
                 "research_strategy": {"literature_max_papers": 10,
                                       "literature_sources": ["zotero", "obsidian"]}},
    )
    prompt = WorkflowEngine()._input_lit("EEG robustness", {}, run)

    assert {Path(item.artifact_path).name for item in results} == {
        "zotero_context.json",
        "obsidian_context.json",
    }
    assert "Library Paper" in prompt
    assert "Internal hypothesis" in prompt
    assert "不是独立科学证据" in prompt


@pytest.mark.asyncio
async def test_overleaf_link_is_persistent_and_remote_url_has_no_secret(tmp_path, monkeypatch):
    paper = tmp_path / "project" / "paper"
    paper.mkdir(parents=True)
    service = OverleafSync(
        tmp_path / "merak.db",
        encryption_secret="test-encryption-secret",
        git_path="git",
    )
    calls = []

    async def fake_git(cwd, *args, timeout=60, project=None):
        calls.append(args)
        if args[:3] == ("remote", "get-url", "overleaf"):
            return "", "missing", 2
        if args[:2] == ("ls-remote", "--symref"):
            return "ref: refs/heads/main\tHEAD\nabc\tHEAD\n", "", 0
        return "", "", 0

    monkeypatch.setattr(service, "_run_git", fake_git)
    result = await service.link_project(
        "project123",
        str(tmp_path / "project"),
        "user@example.test",
        "token-secret-value",
    )

    assert result.success is True
    assert result.branch == "main"
    remote_calls = [
        call for call in calls
        if call[:3] in {
            ("remote", "add", "overleaf"),
            ("remote", "set-url", "overleaf"),
        }
    ]
    assert remote_calls
    assert all("token-secret-value" not in " ".join(call) for call in remote_calls)
    assert all("user@example.test" not in " ".join(call) for call in remote_calls)
    assert b"token-secret-value" not in (tmp_path / "merak.db").read_bytes()

    restored = OverleafSync(
        tmp_path / "merak.db",
        encryption_secret="test-encryption-secret",
        git_path="git",
    )
    status = restored.get_status("project123")
    assert status["linked"] is True
    assert status["credentials_available"] is True
    assert status["branch"] == "main"
    assert restored.is_ready_for_project("project123", str(tmp_path / "project"))


def test_overleaf_export_contains_only_paper_and_figure_trees(tmp_path):
    root = tmp_path / "project"
    paper = root / "paper"
    figures = root / "figures" / "plots"
    repository = root / ".merak" / "overleaf" / "project123" / "repo"
    paper.mkdir(parents=True)
    figures.mkdir(parents=True)
    (paper / "main.tex").write_text(
        "\\graphicspath{{../figures/plots/}}",
        encoding="utf-8",
    )
    (paper / "main.pdf").write_bytes(b"generated")
    (figures / "result.png").write_bytes(b"png")
    (root / "experiments").mkdir()
    (root / "experiments" / "metrics.json").write_text("{}", encoding="utf-8")
    (root / ".env").write_text("SECRET=value", encoding="utf-8")
    service = OverleafSync(
        tmp_path / "merak.db",
        encryption_secret="secret",
        git_path="git",
    )
    project = OverleafProject(
        project_id="project123",
        local_path=str(paper),
        repo_path=str(repository),
    )

    service._materialize_export(project)

    assert (repository / "paper" / "main.tex").is_file()
    assert (repository / "figures" / "plots" / "result.png").is_file()
    assert not (repository / "paper" / "main.pdf").exists()
    assert not (repository / "experiments").exists()
    assert b"SECRET=value" not in b"".join(
        path.read_bytes() for path in repository.rglob("*") if path.is_file()
    )

    (repository / "paper" / "main.tex").write_text("remote edit", encoding="utf-8")
    service._apply_export(project)
    assert (paper / "main.tex").read_text(encoding="utf-8") == "remote edit"


@pytest.mark.asyncio
async def test_overleaf_conflict_aborts_without_choosing_a_side(tmp_path, monkeypatch):
    paper = tmp_path / "paper"
    paper.mkdir()
    service = OverleafSync(
        tmp_path / "merak.db",
        encryption_secret="secret",
        git_path="git",
    )
    project = OverleafProject(
        project_id="project123",
        local_path=str(paper),
        repo_path=str(tmp_path / "repo"),
        email="user@example.test",
        token="token",
        branch="main",
    )
    service._projects[project.project_id] = project
    service._persist(project)
    calls = []

    async def fake_git(cwd, *args, timeout=60, project=None):
        calls.append(args)
        if args[:2] == ("status", "--porcelain"):
            return "", "", 0
        if args[:2] == ("rev-parse", "HEAD"):
            return "abc\n", "", 0
        if args and args[0] == "fetch":
            return "", "", 0
        if args and args[0] == "merge" and "--abort" not in args:
            return "", "conflict", 1
        if args[:3] == ("diff", "--name-only", "--diff-filter=U"):
            return "main.tex\n", "", 0
        return "", "", 0

    monkeypatch.setattr(service, "_run_git", fake_git)
    result = await service.pull("project123")

    assert result.success is False
    assert result.conflicts == ["main.tex"]
    assert ("merge", "--abort") in calls
    assert not any("checkout" in call and "--theirs" in call for call in calls)


@pytest.mark.asyncio
async def test_notification_persists_and_reports_channel_results(tmp_path, monkeypatch):
    service = NotificationService(tmp_path / "notify.db")
    service.update_config(
        feishu_webhook="https://example.test/hook",
        enabled_channels=[NotifyChannel.FEISHU],
    )

    async def sent(*args, **kwargs):
        return None

    monkeypatch.setattr(service, "_send_feishu", sent)
    result = await service.notify("title", "content")

    assert result == {"success": True, "sent": ["feishu"], "errors": {}}
    restored = NotificationService(tmp_path / "notify.db")
    assert restored.public_config()["feishu_webhook"] is True
    assert restored.public_config()["enabled_channels"] == ["feishu"]


@pytest.mark.asyncio
async def test_workflow_notifications_require_a_test_for_current_config(tmp_path, monkeypatch):
    service = NotificationService(tmp_path / "notify.db")
    service.update_config(
        feishu_webhook="https://example.test/hook",
        enabled_channels=[NotifyChannel.FEISHU],
    )
    calls = []

    async def sent(*args, **kwargs):
        calls.append(True)

    monkeypatch.setattr(service, "_send_feishu", sent)
    before_test = await service.workflow_completed("workflow", 10, 2)
    assert before_test["success"] is False
    assert "delivery test" in before_test["errors"]["feishu"]
    assert calls == []

    service._verification_store.record(
        "notification",
        "feishu",
        service.channel_payload(NotifyChannel.FEISHU),
        True,
        "verified",
    )
    after_test = await service.workflow_completed("workflow", 10, 2)
    assert after_test["success"] is True
    assert calls == [True]


@pytest.mark.asyncio
async def test_notification_does_not_treat_api_level_error_as_success(tmp_path, monkeypatch):
    response = httpx.Response(200, json={"code": 19001, "msg": "invalid webhook"})
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *args, **kwargs: FakeHttpClient(response),
    )
    service = NotificationService(tmp_path / "notify.db")
    service.update_config(
        feishu_webhook="https://example.test/hook",
        enabled_channels=[NotifyChannel.FEISHU],
    )

    result = await service.notify("title", "content")

    assert result["success"] is False
    assert result["sent"] == []
    assert "invalid webhook" in result["errors"]["feishu"]


@pytest.mark.asyncio
async def test_incomplete_email_configuration_is_a_failed_delivery(tmp_path):
    service = NotificationService(tmp_path / "notify.db")
    service.update_config(enabled_channels=[NotifyChannel.EMAIL])

    result = await service.notify("title", "content")

    assert result["success"] is False
    assert "incomplete" in result["errors"]["email"].lower()
def test_literature_prompt_separates_survey_limit_from_bibliography_minimum(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    run = WorkflowRun(
        project_path=str(project),
        options={
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
            "target_venue": "ICLR",
            "research_family": "auto",
            "study_archetype": "auto",
            "research_strategy": {"literature_max_papers": 12},
        },
    )

    prompt = WorkflowEngine()._input_lit("EEG foundation model", {}, run)

    assert "详细综述最多纳入 12 篇" in prompt
    assert "references.bib 至少包含 30 条" in prompt
    assert "检索并去重至少 30 条候选" in prompt
