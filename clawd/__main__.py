"""`python -m clawd --socket PATH`: run the floating Clawd until told to quit."""
import argparse
import os
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clawd")
    parser.add_argument("--socket", required=True, help="Unix socket the plugin posts events to")
    parser.add_argument("--project", default="", help="Project name shown in the panel header")
    args = parser.parse_args(argv)

    # Native Wayland cannot keep a window on top or place it; XWayland can (checked on KDE 2026-11-01).
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

    from PySide6.QtWidgets import QApplication

    from clawd.ipc import AlreadyRunning

    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    from clawd.app import build
    from clawd.call import make_call
    from clawd.voice import make_voice

    try:
        rt = build(args.socket, on_quit=app.quit, project=args.project, voice_factory=make_voice, call_factory=make_call)
    except AlreadyRunning:
        return 0  # one Clawd per session
    rt.window.show()
    rt.window.play_intro()
    code = app.exec()
    rt.server.stop()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
