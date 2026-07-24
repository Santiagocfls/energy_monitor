import importlib


def test_desktop_ui_falls_back_when_tk_is_unavailable(monkeypatch):
    module = importlib.import_module("display.desktop_ui")

    class FailingTk:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("no display")

    monkeypatch.setattr(module, "Tk", FailingTk, raising=False)

    ui = module.DesktopUI()

    assert ui._available is False
    assert ui._terminal_fallback is not None
