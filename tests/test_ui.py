"""在 SDL 离屏窗口中测试真实绘制、点击映射、异步决策和重开。"""
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
from concurrent.futures import Future

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import pygame as pg
    from app import App
except ModuleNotFoundError:
    pg = None


@unittest.skipIf(pg is None, "安装 requirements.txt 后可执行图形回归")
class UITest(unittest.TestCase):
    def setUp(self):
        self.app = App()
        self.app.render()

    def tearDown(self):
        self.app.close()

    def click(self, key):
        a = self.app
        a.render()
        rect = next(r for k, r, enabled in a.buttons if k == key and enabled)
        self.click_point(rect.center)

    def click_point(self, pos):
        a = self.app
        v = a.viewport
        actual = (round(v.x+pos[0]*v.w/1440), round(v.y+pos[1]*v.h/900))
        a.handle(pg.event.Event(pg.MOUSEBUTTONDOWN, button=1, pos=actual))
        a.render()

    def playing(self, lord=0):
        a = self.app
        a.start(seed=42)
        a.game.turn = lord
        for yes in (True, False, False):
            a.game.bid(a.game.turn, yes)
        a.render()
        return a.game

    def test_menu_difficulty_and_bid_clicks(self):
        a = self.app
        self.click("difficulty_3")
        self.click("start")
        self.assertEqual(a.game.difficulty, 3)
        a.game.turn = 0
        self.click("yes")
        self.assertEqual(a.game.phase, "rob")
        self.assertEqual(a.game.caller, 0)
        self.click("rules")
        self.assertEqual(a.modal, "rules")
        self.click("close_modal")
        self.assertIsNone(a.modal)

    def test_card_button_feedback_and_mute(self):
        a = self.app
        self.assertTrue(a.audio.available)
        with patch.object(a.audio, "play") as play:
            self.click("difficulty_3")
            play.assert_called_once_with("button")
            play.reset_mock()
            self.playing()
            self.click_point(a.card_hits[-1][1].center)
            play.assert_called_once_with("card")
        self.click("sound")
        self.assertFalse(a.audio.enabled)
        self.assertFalse(pg.mixer.get_busy())
        a.audio.play("card")
        self.assertFalse(pg.mixer.get_busy())
        self.click("sound")
        self.assertTrue(a.audio.enabled)

    def test_audio_device_failure_does_not_block_game(self):
        from sound import Sounds, samples
        for kind in ("card", "button"):
            pcm = samples(kind)
            self.assertGreater(max(map(abs, pcm)), 500)
            self.assertLess(max(map(abs, pcm)), 7000)
            self.assertEqual((pcm[0], pcm[-1]), (0, 0))
        with patch("sound.pg.mixer.init", side_effect=pg.error("模拟无音频设备")):
            with self.assertLogs(level="WARNING"):
                silent = Sounds()
        self.assertFalse(silent.available)
        silent.play("card")
        silent.toggle()
        self.playing()
        self.click("play")
        self.assertIn("先选择", self.app.toast)

    def test_scaled_card_hit_raise_deselect_and_resize(self):
        a = self.app
        g = self.playing()
        for size in ((1280, 800), (1000, 800), (1600, 900), (720, 450)):
            a.handle(pg.event.Event(pg.VIDEORESIZE, w=size[0], h=size[1]))
            a.render()
            card, rect = a.card_hits[-1]
            old_y = rect.y
            self.click_point(rect.center)
            self.assertIn(card, a.selected)
            self.assertEqual(a.card_hits[-1][1].y, old_y-24)
            self.click_point(a.card_hits[-1][1].center)
            self.assertNotIn(card, a.selected)
        card, rect = a.card_hits[-1]
        self.click_point(rect.center)
        self.click("play")
        self.assertNotIn(card, g.hands[0])
        self.assertEqual(g.turn, 1)

    def test_invalid_play_and_lead_pass(self):
        a = self.app
        g = self.playing()
        rev = g.revision
        self.click("play")
        self.assertIn("先选择", a.toast)
        self.assertEqual(g.revision, rev)
        a.act("pass")
        self.assertIn("首出", a.toast)
        self.assertEqual(g.revision, rev)

    def test_hint_future_and_enemy_future(self):
        a = self.app
        g = self.playing()
        self.click("hint")
        a.pending[0].result(timeout=5)
        a.update()
        self.assertTrue(a.selected)
        self.click("play")
        a.next_ai = 0
        a.update()
        self.assertIsNotNone(a.pending)
        a.pending[0].result(timeout=5)
        a.pending = (*a.pending[:5], 0)
        previous = g.revision
        a.update()
        self.assertGreater(g.revision, previous)

    def test_paused_and_stale_results(self):
        a = self.app
        g = self.playing(1)
        a.next_ai = 0
        a.update()
        job = a.pending
        a.mode = "menu"
        job[0].result(timeout=5)
        previous = g.revision
        a.update()
        self.assertEqual(g.revision, previous)
        a.start(seed=8)
        a.pending = (job[0], job[1], a.game.revision, job[3], job[4], 0)
        previous = a.game.revision
        a.update()
        self.assertEqual(a.game.revision, previous)

    def test_preselect_survives_opponent_move(self):
        a = self.app
        g = self.playing(1)
        a.selected = {g.hands[0][-1]}
        before = a.selected.copy()
        result = g.play(1, [g.hands[1][-1]])
        a.changed(g.bomb_serial, result)
        self.assertEqual(a.selected, before)

    def test_no_hint_when_cannot_beat(self):
        a = self.app
        g = self.playing(1)
        g.hands[1] = [53, 54, 1]
        g.play(1, [53, 54])
        g.pass_turn(2)
        a.act("hint")
        a.pending[0].result(timeout=5)
        a.update()
        self.assertFalse(a.selected)
        self.assertIn("没有能压过", a.toast)

    def test_bomb_settlement_and_space_restart(self):
        a = self.app
        g = self.playing()
        g.hands = [[1, 2, 3, 4], [5], [6]]
        a.selected = {1, 2, 3, 4}
        a.act("play")
        self.assertEqual(a.bomb_text, "炸弹！")
        self.assertGreater(a.bomb_until, a.now)
        a.render()
        a.now = a.over_at + .1
        a.render()
        self.assertIn("again", [b[0] for b in a.buttons])
        a.difficulty = 3  # 曾在菜单选其他难度，但同难度重开要遵守当前对局。
        a.handle(pg.event.Event(pg.KEYDOWN, key=pg.K_SPACE))
        self.assertEqual(a.game.phase, "call")
        self.assertEqual(a.game.difficulty, 2)
        self.assertFalse(a.selected)
        self.assertIsNone(a.pending)


if __name__ == "__main__":
    unittest.main()
