from argparse import Namespace
from unittest.mock import MagicMock

from owrap_old.commands.kinds import KIND_REGISTRY
from owrap_old.runner import _cmd_ctx, _cmd_updr
from owrap_old.utils.actions import dispatch_kw


def test_dispatch_kw_ctx_start(monkeypatch):
    mock_runner = MagicMock()
    monkeypatch.setattr(
        "owrap_old.commands.context_manager.CtxWorkerRunner", lambda: mock_runner,
    )
    dispatch_kw(KIND_REGISTRY, "ctx", "start", Namespace())
    mock_runner.run_manual.assert_called_once_with(mode="ctx")


def test_dispatch_kw_ctx_done_with_error(monkeypatch):
    mock_runner = MagicMock()
    monkeypatch.setattr(
        "owrap_old.commands.context_manager.ManualCtxRunner", lambda: mock_runner,
    )
    dispatch_kw(KIND_REGISTRY, "ctx", "done", Namespace(error="model down"))
    mock_runner.done.assert_called_once_with(error="model down")


def test_dispatch_kw_updr_start_with_subproject_and_ctx(monkeypatch):
    mock_runner = MagicMock()
    monkeypatch.setattr(
        "owrap_old.commands.context_manager.CtxWorkerRunner", lambda: mock_runner,
    )
    dispatch_kw(
        KIND_REGISTRY, "updr", "start", Namespace(subproject="sub1", ctx=True),
    )
    mock_runner.run_manual.assert_called_once_with(mode=None, subproject="sub1")


def test_cmd_ctx_routes_done_action(monkeypatch):
    mock_runner = MagicMock()
    monkeypatch.setattr(
        "owrap_old.commands.context_manager.ManualCtxRunner", lambda: mock_runner,
    )
    _cmd_ctx(Namespace(action="done", error="oops"), None, None, False)
    mock_runner.done.assert_called_once_with(error="oops")


def test_cmd_updr_routes_start(monkeypatch):
    mock_runner = MagicMock()
    monkeypatch.setattr(
        "owrap_old.commands.context_manager.CtxWorkerRunner", lambda: mock_runner,
    )
    _cmd_updr(Namespace(subproject=None, ctx=False), None, None, False)
    mock_runner.run_manual.assert_called_once_with(mode="updr", subproject=None)
