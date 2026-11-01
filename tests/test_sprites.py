import os
from typing import get_args

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from clawd.sprites import FPS, FRAMES, H, INTRO, PALETTE, W, render_frame
from clawd.state import State

pytestmark = pytest.mark.usefixtures("qapp")


def test_every_state_has_at_least_two_frames():
    for state in get_args(State):
        assert len(FRAMES[state]) >= 2, state
        assert FPS[state] > 0, state


def test_all_frames_same_dimensions():
    every = [f for frames in FRAMES.values() for f in frames] + list(INTRO)
    for frame in every:
        assert len(frame) == H
        assert all(len(row) == W for row in frame)


def test_every_frame_char_is_in_the_palette():
    every = [f for frames in FRAMES.values() for f in frames] + list(INTRO)
    used = {ch for f in every for row in f for ch in row}
    assert used <= set(PALETTE) | {"."}, used - set(PALETTE)


def test_body_colour_matches_the_mascots_orange():
    assert PALETTE["B"] == (0xD7, 0x77, 0x57, 255)
    assert PALETTE["K"] == (0, 0, 0, 255)


def test_intro_has_frames_and_ends_on_idle_pose():
    assert len(INTRO) >= 4
    assert INTRO[-1] == FRAMES["idle"][0]


def test_render_frame_scales_and_is_transparent_outside_body():
    frame = FRAMES["idle"][0]
    img = render_frame(frame, 4)
    assert (img.width(), img.height()) == (W * 4, H * 4)
    assert img.pixelColor(0, 0).alpha() == 0
    row = next(i for i, r in enumerate(frame) if "B" in r)
    col = frame[row].index("B")
    body = img.pixelColor(col * 4 + 1, row * 4 + 1)
    assert body.alpha() == 255 and body.name() == "#d77757"


def test_face_frame_is_the_head_with_two_eyes():
    from clawd.sprites import face_frame

    face = face_frame()
    assert len(face) == 4 and all(len(r) == 13 for r in face)
    assert sum(row.count("K") for row in face) == 4  # two eyes, two cells tall
    img = render_frame(face, 3)
    assert (img.width(), img.height()) == (39, 12)
