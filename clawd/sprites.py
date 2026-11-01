"""Pixel-art Clawd: frames as data (rows of palette characters) + a renderer.

The base shape (17x10 cells) is traced from a screenshot of the mascot: a wide body,
two black eyes, arms across the middle and four short legs, colour #d77757.
Frames are drawn on a 21x14 canvas so rings, dots and hops have room.
"""
from PySide6.QtGui import QColor, QImage, QPainter

from clawd.state import State

Frame = tuple[str, ...]

W, H = 21, 14
OX, OY = 2, 3  # where the 17x10 base sits on the canvas

PALETTE: dict[str, tuple[int, int, int, int]] = {
    "B": (0xD7, 0x77, 0x57, 255),  # body (sampled from the screenshot)
    "K": (0, 0, 0, 255),  # eyes
    "E": (0xC2, 0x41, 0x3B, 255),  # body when something went wrong
    "G": (0x4A, 0xDE, 0x80, 255),  # listening ring
    "D": (0xCB, 0xD5, 0xE1, 255),  # thinking dots
    "Y": (0xFA, 0xCC, 0x15, 255),  # attention / sparkle
    "W": (0x93, 0xC5, 0xFD, 255),  # sound arcs
}

BASE: tuple[str, ...] = (
    "..BBBBBBBBBBBBB..",
    "..BBBBBBBBBBBBB..",
    "..BBKBBBBBBBKBB..",
    "..BBKBBBBBBBKBB..",
    "BBBBBBBBBBBBBBBBB",
    "BBBBBBBBBBBBBBBBB",
    "..BBBBBBBBBBBBB..",
    "..BBBBBBBBBBBBB..",
    "..B.B.......B.B..",
    "..B.B.......B.B..",
)
_EYE_COLS = (4, 12)
_ARMS = ((0, 1), (15, 16))  # left, right columns of the arm row
_ARM_ROWS = (4, 5)

Canvas = list[list[str]]


def _canvas() -> Canvas:
    return [["."] * W for _ in range(H)]


def _set(c: Canvas, x: int, y: int, ch: str) -> None:
    if 0 <= x < W and 0 <= y < H:
        c[y][x] = ch


def _sprite(dx: int = 0, dy: int = 0, body: str = "B") -> Canvas:
    c = _canvas()
    for r, row in enumerate(BASE):
        for col, ch in enumerate(row):
            if ch != ".":
                _set(c, OX + col + dx, OY + r + dy, body if ch == "B" else ch)
    return c


def _eyes(c: Canvas, look: int = 0, blink: bool = False, dx: int = 0, dy: int = 0, body: str = "B") -> None:
    """Move the eyes by `look` columns, or blink (one row tall)."""
    for col in _EYE_COLS:
        for row in (2, 3):
            _set(c, OX + col + dx, OY + row + dy, body)
        for row in ((3,) if blink else (2, 3)):
            _set(c, OX + col + look + dx, OY + row + dy, "K")


def _arms(c: Canvas, left: int = 0, right: int = 0, dy: int = 0) -> None:
    """Raise (negative) or lower (positive) each arm by whole rows."""
    for cols, shift in zip(_ARMS, (left, right)):
        for col in range(cols[0], cols[1] + 1):
            for row in _ARM_ROWS:
                _set(c, OX + col, OY + row + dy, ".")
        for col in range(cols[0], cols[1] + 1):
            for row in _ARM_ROWS:
                _set(c, OX + col, OY + row + dy + shift, "B")


def _dots(c: Canvas, count: int) -> None:
    for i in range(count):
        _set(c, OX + 6 + i * 2, 1, "D")


def _freeze(c: Canvas) -> Frame:
    return tuple("".join(row) for row in c)


def _idle(dy: int = 0, blink: bool = False) -> Frame:
    c = _sprite(dy=dy)
    if blink:
        _eyes(c, blink=True, dy=dy)
    return _freeze(c)


def _listening(big: bool) -> Frame:
    c = _sprite()
    _arms(c, left=-2, right=-2)
    ring = [(1, 7), (19, 7)] + ([(0, 7), (20, 7), (1, 6), (19, 6), (1, 8), (19, 8)] if big else [])
    if big:
        ring += [(x, 1) for x in (9, 10, 11)]
    for x, y in ring:
        _set(c, x, y, "G")
    return _freeze(c)


def _thinking(look: int, dots: int) -> Frame:
    c = _sprite()
    _eyes(c, look=look)
    _dots(c, dots)
    return _freeze(c)


def _working(left: int, right: int, dy: int) -> Frame:
    c = _sprite(dy=dy)
    _arms(c, left=left, right=right, dy=dy)
    return _freeze(c)


def _waiting(alert: bool) -> Frame:
    c = _sprite()
    _eyes(c, look=1)
    if alert:
        for y in (0, 1):
            _set(c, 10, y, "Y")
    return _freeze(c)


def _speaking(big: bool) -> Frame:
    c = _sprite(dy=-1 if big else 0)
    arcs = [(19, 5), (19, 6)] + ([(19, 4), (19, 7), (20, 5), (20, 6)] if big else [])
    for x, y in arcs:
        _set(c, x, y, "W")
    return _freeze(c)


def _error(dx: int) -> Frame:
    c = _sprite(dx=dx, body="E")
    return _freeze(c)


def _done(dy: int, sparkle: bool) -> Frame:
    c = _sprite(dy=dy)
    if sparkle:
        for x, y in ((1, 1), (19, 2), (10, 0)):
            _set(c, x, y, "Y")
    return _freeze(c)


FRAMES: dict[State, list[Frame]] = {
    "idle": [_idle(), _idle(-1), _idle(), _idle(blink=True)],
    "listening": [_listening(False), _listening(True)],
    "thinking": [_thinking(-1, 1), _thinking(1, 2), _thinking(-1, 3), _thinking(1, 0)],
    "working": [_working(-1, 0, 0), _working(0, -1, -1), _working(-1, 0, 0), _working(0, -1, 0)],
    "waiting": [_waiting(True), _waiting(False)],
    "speaking": [_speaking(False), _speaking(True)],
    "error": [_error(-1), _error(1), _error(-1), _error(1)],
    "done": [_done(-2, True), _done(-1, True), _done(0, False), _done(0, False)],
}

FPS: dict[State, int] = {
    "idle": 3,
    "listening": 4,
    "thinking": 3,
    "working": 6,
    "waiting": 2,
    "speaking": 5,
    "error": 8,
    "done": 6,
}

# Pop-in: rises from the bottom edge, bounces once, lands on the first idle pose.
INTRO: list[Frame] = [_idle(dy) for dy in (10, 6, 3, 0, -2)] + [FRAMES["idle"][0]]
INTRO_FPS = 10


def face_frame() -> Frame:
    """Just the head of the idle pose (body and two eyes), for the panel's portrait."""
    idle = FRAMES["idle"][0]
    return tuple(row[OX + 2 : OX + 15] for row in idle[OY : OY + 4])


def render_frame(frame: Frame, scale: int) -> QImage:
    """Nearest-neighbour render on a transparent background."""
    img = QImage(len(frame[0]) * scale, len(frame) * scale, QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    painter = QPainter(img)
    for y, row in enumerate(frame):
        for x, ch in enumerate(row):
            if ch != ".":
                r, g, b, a = PALETTE[ch]
                painter.fillRect(x * scale, y * scale, scale, scale, QColor(r, g, b, a))
    painter.end()
    return img
