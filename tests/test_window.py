import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtTest import QTest

from clawd.sprites import INTRO
from clawd.view import View
from clawd.window import ClawdWindow, clamp_to_screens, stepped_polygon


@pytest.fixture
def win(qtbot, tmp_path):
    w = ClawdWindow(state_path=tmp_path / "state.json")
    qtbot.addWidget(w)
    return w


def test_flags_frameless_transparent_on_top_no_focus(win):
    flags = win.windowFlags()
    assert flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.WindowStaysOnTopHint
    assert flags & Qt.WindowType.WindowDoesNotAcceptFocus
    assert win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert win.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)


def test_panel_shows_live_transcript_and_keeps_it_after_final(win):
    win.set_transcript("run the", False)
    assert win.transcript_text() == "run the"
    win.set_transcript("run the tests", True)
    assert win.transcript_text() == "run the tests"


def test_apply_view_shows_badge_ticker_headline_body_and_stats(win):
    win.show()
    win.apply_view(
        View(badge="DONE", accent="green", headline="Done.", body="Pagination is in.", stats="4 actions · 2 s")
    )
    assert win.badge_text() == "DONE"
    assert win.headline_text() == "Done."
    assert win.body_text() == "Pagination is in."
    assert "4 actions · 2 s" in win.stats_line()
    assert not win.ticker_line()
    win.apply_view(View(badge="WORKING", accent="orange", ticker="EDITS gigs.ts"))
    assert win.ticker_line() == "EDITS gigs.ts"
    assert not win.headline_text() and not win.body_text()


def test_empty_parts_of_a_view_take_no_room(win):
    win.show()
    win.apply_view(View(badge="IDLE", accent="dim"))
    bare = win.height()
    win.apply_view(View(badge="DONE", accent="green", headline="Done.", body="Pagination is in.", stats="2 s"))
    assert win.height() > bare


def test_accent_colours_the_badge(win):
    win.apply_view(View(badge="NEEDS YOU", accent="yellow"))
    assert "#facc15" in win.badge_style()


def test_project_name_shows_in_the_header(win):
    assert win.project_text() == "CLAWD"
    win.set_project("gigs-api")
    assert win.project_text() == "CLAWD / gigs-api"


def test_stepped_corner_polygon_cuts_the_corners_in_two_steps():
    poly = stepped_polygon(QRect(0, 0, 100, 50))
    pts = [(poly.at(i).x(), poly.at(i).y()) for i in range(poly.count())]
    assert pts[0] == (0, 8) and pts[4] == (8, 0) and len(pts) == 20
    assert all(0 <= x <= 100 and 0 <= y <= 50 for x, y in pts)


def test_clamp_moves_offscreen_position_onto_a_screen():
    screens = [QRect(0, 0, 1920, 1080)]
    size = QSize(300, 100)
    assert clamp_to_screens(QPoint(5000, 5000), size, screens) == QPoint(1620, 980)
    assert clamp_to_screens(QPoint(-50, -50), size, screens) == QPoint(0, 0)
    assert clamp_to_screens(QPoint(100, 100), size, screens) == QPoint(100, 100)


def test_clamp_keeps_a_position_on_a_second_screen():
    screens = [QRect(0, 0, 1920, 1080), QRect(1920, 0, 1920, 1080)]
    assert clamp_to_screens(QPoint(2500, 200), QSize(300, 100), screens) == QPoint(2500, 200)


def test_saved_offscreen_position_is_clamped_on_load(qtbot, tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"x": 99999, "y": 99999}))
    w = ClawdWindow(state_path=path, screens=[QRect(0, 0, 1920, 1080)])
    qtbot.addWidget(w)
    assert w.pos().x() <= 1920 - w.width() and w.pos().y() <= 1080 - w.height()


def test_position_is_saved_without_secrets(win, tmp_path):
    win.save_state()
    data = json.loads((tmp_path / "state.json").read_text())
    assert set(data) == {"x", "y", "panel_visible"}


def test_animation_timer_paused_when_hidden(win):
    win.show()
    assert win.timer_active()
    win.hide()
    assert not win.timer_active()
    win.show()
    assert win.timer_active()


def test_mute_button_emits_mute_toggled(win, qtbot):
    with qtbot.waitSignal(win.mute_toggled) as first:
        win.mute_button.click()
    assert first.args == [True]
    with qtbot.waitSignal(win.mute_toggled) as second:
        win.mute_button.click()
    assert second.args == [False]


def test_close_button_emits_closed(win, qtbot):
    with qtbot.waitSignal(win.closed):
        win.close_button.click()


def test_clicking_the_sprite_emits_clicked(win, qtbot):
    win.show()
    with qtbot.waitSignal(win.clicked):
        QTest.mouseClick(win.sprite, Qt.MouseButton.LeftButton, pos=win.sprite.rect().center())


def test_right_click_toggles_the_panel(win):
    win.show()
    assert win.panel.isVisible()
    QTest.mouseClick(win.sprite, Qt.MouseButton.RightButton, pos=win.sprite.rect().center())
    assert not win.panel.isVisible()
    QTest.mouseClick(win.sprite, Qt.MouseButton.RightButton, pos=win.sprite.rect().center())
    assert win.panel.isVisible()


def test_intro_plays_through_then_idle(win):
    win.play_intro()
    assert win.is_intro
    for _ in range(len(INTRO)):
        win.advance()
    assert not win.is_intro


def test_empty_window_area_is_click_through(win):
    win.show()
    mask = win.mask()
    assert mask.contains(win.sprite.geometry().center())
    assert mask.contains(win.panel.geometry().center())
    assert not mask.contains(QPoint(2, win.height() - 2))  # beside the sprite, below the bubble


def test_pending_row_buttons_emit_send_cancel_and_edited(win, qtbot):
    win.show()
    win.set_pending("list the files", 2.5)
    assert win.pending_row.isVisible()
    with qtbot.waitSignal(win.send_pressed):
        win.send_button.click()
    with qtbot.waitSignal(win.cancel_pressed):
        win.cancel_button.click()
    with qtbot.waitSignal(win.edited) as sig:
        win.pending_edit.setText("list all files")
        win.pending_edit.editingFinished.emit()
    assert sig.args == ["list all files"]
    win.set_pending(None)
    assert not win.pending_row.isVisible()


def test_empty_transcript_takes_no_room_until_set(win):
    win.show()
    empty_height = win.height()
    assert not win.transcript_label.isVisibleTo(win)
    win.set_transcript("run the tests", True)
    assert win.transcript_label.isVisibleTo(win)
    assert win.height() > empty_height

def test_a_pending_request_always_shows_the_panel_so_it_can_be_cancelled(win):
    win.show()
    QTest.mouseClick(win.sprite, Qt.MouseButton.RightButton, pos=win.sprite.rect().center())
    assert not win.panel.isVisible()
    win.set_pending("list the files", 2.0)
    assert win.panel.isVisible() and win.pending_row.isVisible()
    # and hiding it again is refused while the countdown runs
    QTest.mouseClick(win.sprite, Qt.MouseButton.RightButton, pos=win.sprite.rect().center())
    assert win.panel.isVisible()
    win.set_pending(None)
    QTest.mouseClick(win.sprite, Qt.MouseButton.RightButton, pos=win.sprite.rect().center())
    assert not win.panel.isVisible()


def test_live_tag_shows_whether_the_mic_is_open(win):
    assert win.live_text() == ""  # no call yet: no tag
    win.set_live(True)
    assert win.live_text() == "LIVE"
    win.set_live(False)
    assert win.live_text() == "MUTED"


def _pixel_in_window(win, widget, x, y):
    """The colour of the rendered window at (x, y) inside `widget`."""
    point = widget.mapTo(win, QPoint(x, y))
    return win.grab().toImage().pixelColor(point.x(), point.y()).name()


def test_the_quote_bar_is_drawn_beside_the_body_in_the_accent_colour(win):
    win.show()
    win.apply_view(View(badge="WORKING", accent="orange", body="Added GET /gigs with cursor pagination."))
    body = win._body
    assert _pixel_in_window(win, body, 1, body.height() // 2) == "#d77757"
    win.apply_view(View(badge="DONE", accent="green", body="Added GET /gigs with cursor pagination."))
    assert _pixel_in_window(win, body, 1, body.height() // 2) == "#4ade80"
    # and the text itself is pushed to the right of the bar
    assert _pixel_in_window(win, body, 40, body.height() // 2) != "#4ade80"


def test_the_quote_bar_is_not_drawn_when_there_is_no_body(win):
    win.show()
    win.apply_view(View(badge="WORKING", accent="orange", ticker="EDITS gigs.ts"))
    assert not win._body.isVisible()


def test_the_usage_line_shows_with_its_level_colour_and_hides_without_data(win):
    win.show()
    win.apply_view(View(badge="IDLE", accent="dim", usage="Claude 5h 34% · week 82%", usage_level="warn"))
    assert win.usage_line() == "Claude 5h 34% · week 82%" and "#facc15" in win.usage_style()
    win.apply_view(View(badge="IDLE", accent="dim", usage="Claude week 97%", usage_level="high"))
    assert "#f0605a" in win.usage_style()
    win.apply_view(View(badge="IDLE", accent="dim", usage="Claude 5h 10%", usage_level="ok"))
    assert "#facc15" not in win.usage_style() and "#f0605a" not in win.usage_style()
    win.apply_view(View(badge="IDLE", accent="dim"))
    assert win.usage_line() == "" and not win._usage.isVisible()
