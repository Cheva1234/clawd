"""The floating Clawd: sprite + a speech-bubble panel in a frameless, transparent, always-on-top window."""
import json
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QMouseEvent, QPainter, QPolygon, QRegion
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from clawd.sprites import FPS, FRAMES, INTRO, INTRO_FPS, H, W, Frame, face_frame, render_frame
from clawd.state import State
from clawd.view import View

DEFAULT_STATE_PATH = Path.home() / ".config" / "cheva-clawd" / "state.json"
_DRAG_THRESHOLD = 6
BUBBLE_WIDTH = 276
TAIL_H = 10
PANEL_BG = "#0f141f"
ACCENT = {
    "orange": "#d77757",
    "green": "#4ade80",
    "yellow": "#facc15",
    "violet": "#a78bfa",
    "red": "#f0605a",
    "dim": "#3b4660",
    "blue": "#93c5fd",
}
_MONO = "font-family: monospace; font-weight: bold;"

_STYLE = """
QLabel { color: #cdd3e0; font-size: 12px; }
QPushButton { background: #1e293b; color: #cdd3e0; border: 2px solid #2d3750; padding: 0px 6px; font-size: 11px; }
QPushButton:checked { background: #7f1d1d; }
QLineEdit { background: #0b0f18; color: #e2e8f0; border: 2px solid #2d3750; padding: 2px 4px; }
"""


def clamp_to_screens(pos: QPoint, size: QSize, screens: list[QRect]) -> QPoint:
    """Return `pos` moved so a window of `size` lies fully on one screen."""
    if not screens:
        return pos
    center = QPoint(pos.x() + size.width() // 2, pos.y() + size.height() // 2)

    def distance(r: QRect) -> int:
        dx = max(r.left() - center.x(), 0, center.x() - r.right())
        dy = max(r.top() - center.y(), 0, center.y() - r.bottom())
        return dx * dx + dy * dy

    screen = min(screens, key=distance)
    x = min(max(pos.x(), screen.left()), screen.right() + 1 - size.width())
    y = min(max(pos.y(), screen.top()), screen.bottom() + 1 - size.height())
    return QPoint(max(x, screen.left()), max(y, screen.top()))


def stepped_polygon(rect: QRect, step: int = 4) -> QPolygon:
    """A rectangle whose four corners are cut in two square steps (the pixel-art bubble shape)."""
    a, b = 2 * step, step
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    pts = [
        (0, a), (b, a), (b, b), (a, b), (a, 0),
        (w - a, 0), (w - a, b), (w - b, b), (w - b, a), (w, a),
        (w, h - a), (w - b, h - a), (w - b, h - b), (w - a, h - b), (w - a, h),
        (a, h), (a, h - b), (b, h - b), (b, h - a), (0, h - a),
    ]  # fmt: skip
    return QPolygon([QPoint(x + px, y + py) for px, py in pts])


class _Bubble(QWidget):
    """Draws the stepped frame in the accent colour, with a tail pointing down at Clawd."""

    def __init__(self) -> None:
        super().__init__()
        self._accent = "dim"
        self._tail_x = BUBBLE_WIDTH - 40
        self.setFixedWidth(BUBBLE_WIDTH)

    def set_accent(self, accent: str) -> None:
        self._accent = accent
        self.update()

    def set_tail_x(self, x: int) -> None:
        self._tail_x = x
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setPen(Qt.PenStyle.NoPen)
        body = QRect(0, 0, self.width(), self.height() - TAIL_H)
        accent = QColor(ACCENT[self._accent])
        p.setBrush(accent)
        p.drawPolygon(stepped_polygon(body))
        p.setBrush(QColor(PANEL_BG))
        p.drawPolygon(stepped_polygon(body.adjusted(2, 2, -2, -2)))
        p.setBrush(accent)
        for i, half in enumerate((10, 7, 4, 1)):  # the tail: four square steps narrowing downward
            p.drawRect(self._tail_x - half, body.height() - 2 + i * 3, half * 2, 3)


class _Quote(QLabel):
    """The summary text with an accent-coloured bar on its left (Qt stylesheet borders do not paint here)."""

    BAR = 3

    def __init__(self) -> None:
        super().__init__("")
        self._accent = QColor(ACCENT["dim"])
        self.setContentsMargins(self.BAR + 8, 2, 0, 2)

    def set_accent(self, color: str) -> None:
        self._accent = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        QPainter(self).fillRect(0, 2, self.BAR, max(0, self.height() - 4), self._accent)


class _Face(QWidget):
    """The portrait: Clawd's head on a small dark tile."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(44, 44)
        self._img = render_frame(face_frame(), 3)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#2d3750"))
        p.fillRect(self.rect().adjusted(2, 2, -2, -2), QColor("#1c2436"))
        p.drawImage((self.width() - self._img.width()) // 2, (self.height() - self._img.height()) // 2, self._img)


class _Sprite(QWidget):
    """Draws the current frame; left click = clicked, drag = move window, right click = toggle panel."""

    clicked = Signal()
    toggle_panel = Signal()
    drag_finished = Signal()

    def __init__(self, scale: int):
        super().__init__()
        self._scale = scale
        self._frame: Frame = FRAMES["idle"][0]
        self._cache: dict[Frame, QImage] = {}
        self._press: QPoint | None = None
        self._dragging = False
        self.setFixedSize(W * scale, H * scale)

    def set_frame(self, frame: Frame) -> None:
        self._frame = frame
        self.update()

    def paintEvent(self, _event) -> None:
        img = self._cache.get(self._frame)
        if img is None:
            img = self._cache[self._frame] = render_frame(self._frame, self._scale)
        painter = QPainter(self)
        painter.drawImage(0, 0, img)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.RightButton:
            self.toggle_panel.emit()
        elif e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position().toPoint()
            self._dragging = False

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._press is None or self._dragging:
            return
        if (e.position().toPoint() - self._press).manhattanLength() >= _DRAG_THRESHOLD:
            self._dragging = True
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton or self._press is None:
            return
        was_drag = self._dragging
        self._press = None
        self._dragging = False
        if was_drag:
            self.drag_finished.emit()
        else:
            self.clicked.emit()


class _EditLine(QLineEdit):
    wants_focus = Signal()

    def mousePressEvent(self, e: QMouseEvent) -> None:
        self.wants_focus.emit()
        super().mousePressEvent(e)


class ClawdWindow(QWidget):
    clicked = Signal()
    closed = Signal()
    mute_toggled = Signal(bool)
    send_pressed = Signal()
    cancel_pressed = Signal()
    edited = Signal(str)

    def __init__(
        self,
        scale: int = 4,
        state_path: Path | None = None,
        screens: list[QRect] | None = None,
    ):
        super().__init__()
        self._state_path = state_path or DEFAULT_STATE_PATH
        self._screens = screens
        self._state: State = "idle"
        self._frame_i = 0
        self._intro_i = 0
        self._intro = False
        self._transcript = ""
        self._name_plain = "CLAWD"
        self._live_text = ""

        self.setWindowTitle("Clawd")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet(_STYLE)

        self.sprite = _Sprite(scale)
        self.panel = self._build_panel()
        self._col = QVBoxLayout(self)
        self._col.setContentsMargins(0, 0, 0, 0)
        self._col.setSpacing(0)
        self._col.addWidget(self.panel)
        self._col.addWidget(self.sprite, 0, Qt.AlignmentFlag.AlignRight)
        self.panel.set_tail_x(BUBBLE_WIDTH - self.sprite.width() // 2)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.advance)
        self.sprite.clicked.connect(self.clicked)
        self.sprite.toggle_panel.connect(self._toggle_panel)
        self.sprite.drag_finished.connect(self.save_state)

        self.set_project("")
        self.apply_view(View(badge="IDLE", accent="dim"))
        self._load_state()
        self.set_state("idle")

    # --- building -------------------------------------------------------
    def _build_panel(self) -> _Bubble:
        panel = _Bubble()
        col = QVBoxLayout(panel)
        col.setContentsMargins(16, 14, 16, 14 + TAIL_H)
        col.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(10)
        self._name = QLabel("CLAWD")
        self._badge = QLabel("IDLE")
        self._live_tag = QLabel("")
        self._live_tag.hide()
        meta = QVBoxLayout()
        meta.setSpacing(3)
        meta.addWidget(self._name)
        badge_row = QHBoxLayout()
        badge_row.addWidget(self._badge)
        badge_row.addWidget(self._live_tag)
        badge_row.addStretch(1)
        meta.addLayout(badge_row)
        self.mute_button = QPushButton("mute")
        self.mute_button.setCheckable(True)
        self.mute_button.toggled.connect(self._on_mute_toggled)
        self.close_button = QPushButton("×")
        self.close_button.clicked.connect(self.closed)
        buttons = QVBoxLayout()
        buttons.setSpacing(3)
        buttons.addWidget(self.mute_button)
        buttons.addWidget(self.close_button)
        head.addWidget(_Face())
        head.addLayout(meta, 1)
        head.addLayout(buttons)
        col.addLayout(head)

        self._ticker = QLabel("")
        self._headline = QLabel("")
        self._headline.setWordWrap(True)
        self._body = _Quote()
        self._body.setWordWrap(True)
        self._stats = QLabel("")
        self.transcript_label = QLabel("")
        self.transcript_label.setWordWrap(True)
        for label in (self._ticker, self._headline, self._body, self._stats, self.transcript_label):
            label.hide()
            col.addWidget(label)

        self.pending_row = QWidget()
        pend = QVBoxLayout(self.pending_row)
        pend.setContentsMargins(0, 2, 0, 0)
        pend.setSpacing(3)
        self.pending_edit = _EditLine()
        self.pending_edit.wants_focus.connect(lambda: self._allow_focus(True))
        self.pending_edit.editingFinished.connect(self._on_edit_finished)
        row = QHBoxLayout()
        self._countdown = QLabel("")
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.send_pressed)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_pressed)
        row.addWidget(self._countdown, 1)
        row.addWidget(self.send_button)
        row.addWidget(self.cancel_button)
        pend.addWidget(self.pending_edit)
        pend.addLayout(row)
        self.pending_row.hide()
        col.addWidget(self.pending_row)
        return panel

    # --- public API -----------------------------------------------------
    def set_state(self, state: State, tool: str | None = None) -> None:
        """Pick the sprite animation. (What the panel says comes from `apply_view`.)"""
        self._state = state
        self._frame_i = 0
        if not self._intro:
            self._show_frame()
            self._retime(FPS[state])

    def apply_view(self, view: View) -> None:
        color = ACCENT[view.accent]
        self._badge.setText(view.badge)
        self._badge.setStyleSheet(f"background: {color}; color: #0b0f18; {_MONO} font-size: 10px; padding: 2px 7px;")
        self.panel.set_accent(view.accent)
        self._set_text(self._ticker, view.ticker, f"color: {color}; {_MONO} font-size: 11px;")
        self._set_text(self._headline, view.headline, "color: #f1f5f9; font-size: 15px; font-weight: bold;")
        self._body.set_accent(color)
        self._set_text(self._body, view.body, "color: #cdd3e0;")
        self._set_text(
            self._stats, f"◆ {view.stats}" if view.stats else None, f"color: {color}; {_MONO} font-size: 11px;"
        )
        self._refresh_layout()

    def set_project(self, name: str) -> None:
        self._name_plain = f"CLAWD / {name}" if name else "CLAWD"
        self._name.setText(
            f"<span style='color:#f1f5f9;{_MONO}'>CLAWD</span>"
            + (f" <span style='color:#8b95ab'>/ {name}</span>" if name else "")
        )
        self._refresh_layout()

    def set_live(self, live: bool) -> None:
        """Show whether the mic is open: the call is live, or hung up (muted)."""
        self._live_text = "LIVE" if live else "MUTED"
        color = ACCENT["green"] if live else ACCENT["dim"]
        self._live_tag.setText(f"● {self._live_text}" if live else self._live_text)
        self._live_tag.setStyleSheet(f"color: {color}; {_MONO} font-size: 10px;")
        self._live_tag.show()
        self._refresh_layout()

    def live_text(self) -> str:
        return self._live_text

    def set_transcript(self, text: str, final: bool) -> None:
        self._transcript = text
        self.transcript_label.setText(f"You: {text}" if final else f"You: {text} …")
        self.transcript_label.setStyleSheet("color: #cdd3e0;" if final else "color: #94a3b8; font-style: italic;")
        self.transcript_label.setVisible(bool(text))
        self._refresh_layout()

    def set_muted(self, muted: bool) -> None:
        self.mute_button.blockSignals(True)
        self.mute_button.setChecked(muted)
        self.mute_button.setText("unmute" if muted else "mute")
        self.mute_button.blockSignals(False)

    def set_pending(self, text: str | None, seconds_left: float = 0.0) -> None:
        if text is None:
            self.pending_row.hide()
        else:
            if not self.pending_edit.hasFocus() and self.pending_edit.text() != text:
                self.pending_edit.setText(text)
            self._countdown.setText(f"sending in {seconds_left:.0f}s")
            self.pending_row.show()
            self.panel.show()  # the Cancel button must be visible while a request counts down
        self._refresh_layout()

    def play_intro(self) -> None:
        self._intro = True
        self._intro_i = 0
        self.sprite.set_frame(INTRO[0])
        self._retime(INTRO_FPS)

    def advance(self) -> None:
        """One animation tick (called by the timer; public for tests)."""
        if self._intro:
            self._intro_i += 1
            if self._intro_i >= len(INTRO):
                self._intro = False
                self.set_state(self._state)
                return
            self.sprite.set_frame(INTRO[self._intro_i])
            return
        self._frame_i = (self._frame_i + 1) % len(FRAMES[self._state])
        self._show_frame()

    @property
    def is_intro(self) -> bool:
        return self._intro

    def transcript_text(self) -> str:
        return self._transcript

    def badge_text(self) -> str:
        return self._badge.text()

    def badge_style(self) -> str:
        return self._badge.styleSheet()

    def ticker_line(self) -> str:
        return self._ticker.text()

    def headline_text(self) -> str:
        return self._headline.text()

    def body_text(self) -> str:
        return self._body.text()

    def stats_line(self) -> str:
        return self._stats.text()

    def project_text(self) -> str:
        return self._name_plain

    def timer_active(self) -> bool:
        return self._timer.isActive()

    def save_state(self) -> None:
        data = {"x": self.x(), "y": self.y(), "panel_visible": self.panel.isVisibleTo(self)}
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps(data))
        except OSError:
            pass  # position memory is a nicety; never crash the pet over it

    # --- internals ------------------------------------------------------
    @staticmethod
    def _set_text(label: QLabel, text: str | None, style: str) -> None:
        label.setText(text or "")
        label.setStyleSheet(style)
        label.setVisible(bool(text))

    def _screen_rects(self) -> list[QRect]:
        if self._screens is not None:
            return self._screens
        return [s.availableGeometry() for s in QGuiApplication.screens()]

    def _load_state(self) -> None:
        data: dict = {}
        try:
            data = json.loads(self._state_path.read_text())
        except (OSError, ValueError):
            pass
        if data.get("panel_visible") is False:
            self.panel.hide()
        self.adjustSize()
        rects = self._screen_rects()
        if "x" in data and "y" in data:
            pos = QPoint(int(data["x"]), int(data["y"]))
        elif rects:
            pos = QPoint(rects[0].right() - self.width() - 24, rects[0].bottom() - self.height() - 24)
        else:
            return
        self.move(clamp_to_screens(pos, self.size(), rects))

    def _show_frame(self) -> None:
        self.sprite.set_frame(FRAMES[self._state][self._frame_i])

    def _retime(self, fps: int) -> None:
        self._timer.setInterval(max(1, 1000 // fps))

    def _on_mute_toggled(self, muted: bool) -> None:
        self.mute_button.setText("unmute" if muted else "mute")
        self.mute_toggled.emit(muted)

    def _toggle_panel(self) -> None:
        if self.pending_row.isVisibleTo(self):
            return  # never hide the Cancel button while a request is about to be sent
        self.panel.setVisible(not self.panel.isVisible())
        self._refresh_layout()
        self.save_state()

    def _refresh_layout(self) -> None:
        bottom_right = self.geometry().bottomRight()
        self._col.activate()
        lay = self.panel.layout()
        if lay is not None:
            lay.activate()
        self.adjustSize()
        # keep the pet where it is: grow/shrink to the left and upward
        self.move(bottom_right.x() - self.width() + 1, bottom_right.y() - self.height() + 1)
        self._update_mask()

    def _update_mask(self) -> None:
        region = QRegion(self.sprite.geometry())
        if self.panel.isVisibleTo(self):
            region = region.united(QRegion(self.panel.geometry()))
        self.setMask(region)

    def _allow_focus(self, allow: bool) -> None:
        """Typing into the edit box needs focus; drop the no-focus flag only while editing."""
        flags = self.windowFlags()
        want = flags & ~Qt.WindowType.WindowDoesNotAcceptFocus if allow else flags | Qt.WindowType.WindowDoesNotAcceptFocus
        if want != flags:
            self.setWindowFlags(want)
            self.show()
            if allow:
                self.activateWindow()

    def _on_edit_finished(self) -> None:
        self.edited.emit(self.pending_edit.text())
        self._allow_focus(False)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._col.activate()
        self._update_mask()
        self._timer.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._timer.stop()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_mask()

    def closeEvent(self, event) -> None:
        self.save_state()
        super().closeEvent(event)
