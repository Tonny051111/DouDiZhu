"""Pygame 桌面牌桌。所有坐标共用 1440×900 逻辑画布；窗口等比适配。"""
import logging
import math
import os
import platform
from pathlib import Path
import random
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame as pg
import ai
from sound import Sounds
from core import Game, DIFFICULTIES, RANK_TEXT, rank, counts, classify, beats, cards_for, legal_moves, same_team

W, H = 1440, 900
INK = (12, 30, 37)
PANEL = (21, 47, 55)
EDGE = (48, 80, 86)
GOLD = (234, 197, 125)
CREAM = (247, 241, 224)
MUTED = (151, 178, 179)
TEAL = (106, 205, 185)
RED = (192, 72, 74)
NAMES = ("你", "电脑1", "电脑2")
AUTHOR = "Tonny陳"


def find_font():
    override = os.environ.get("DDZ_FONT")
    candidates = [override, str(Path(__file__).with_name("assets") / "font.ttf"),
                  "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
                  "/System/Library/Fonts/PingFang.ttc",
                  "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    for name in ("microsoftyahei", "pingfangsc", "notosanscjksc", "wenquanyimicrohei", "simhei"):
        path = pg.font.match_font(name)
        if path:
            return path
    raise RuntimeError("未找到中文字体。请将中文字体放到 assets/font.ttf，或用 DDZ_FONT 环境变量指定字体路径。")


class App:
    def __init__(self, size=(1280, 800)):
        pg.display.init()
        pg.font.init()
        self.audio = Sounds()
        self.screen = pg.display.set_mode(size, pg.RESIZABLE)
        pg.display.set_caption("三人经典斗地主 · 单人对战")
        self.canvas = pg.Surface((W, H))
        self.font_path = find_font()
        self.fonts = {}
        self.text_cache = {}
        self.clock = pg.time.Clock()
        self.running = True
        self.game = None
        self.mode = "menu"
        self.modal = None
        self.difficulty = 2
        self.selected = set()
        self.buttons = []
        self.card_hits = []
        self.mouse = (-1, -1)
        self.toast = ""
        self.toast_until = 0
        self.now = time.monotonic()
        self.next_ai = self.now
        self.bomb_until = self.over_at = 0
        self.bomb_text = ""
        self.epoch = 0
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ddz-ai")
        self.pending = None
        self.decision_rng = random.Random()
        self.hint_revision = -1
        self.hint_index = 0
        self.hint_moves = []
        self.viewport = pg.Rect(0, 0, *size)
        self.background = self.make_background()
        icon = pg.Surface((48, 48))
        icon.fill(INK)
        pg.draw.polygon(icon, GOLD, [(24, 5), (43, 24), (24, 43), (5, 24)])
        pg.display.set_icon(icon)

    def font(self, size):
        if size not in self.fonts:
            self.fonts[size] = pg.font.Font(self.font_path, size)
        return self.fonts[size]

    def text(self, value, x, y, size=22, color=CREAM, anchor="topleft"):
        value = str(value)
        key = (value, size, color)
        surface = self.text_cache.get(key)
        if surface is None:
            surface = self.font(size).render(value, True, color)
            if len(self.text_cache) > 1600:
                self.text_cache.clear()
            self.text_cache[key] = surface
        rect = surface.get_rect(**{anchor: (round(x), round(y))})
        self.canvas.blit(surface, rect)
        return rect

    def panel(self, rect, color=PANEL, border=EDGE, radius=16):
        rect = pg.Rect(rect)
        pg.draw.rect(self.canvas, color, rect, border_radius=radius)
        if border:
            pg.draw.rect(self.canvas, border, rect, 1, border_radius=radius)
        return rect

    def button(self, key, label, rect, primary=False, enabled=True, selected=False):
        rect = pg.Rect(rect)
        hover = rect.collidepoint(self.mouse) and enabled
        color = GOLD if primary or selected else PANEL
        if not enabled:
            color = (25, 45, 52)
        elif hover:
            color = (248, 214, 151) if primary or selected else (39, 73, 81)
        self.panel(rect, color, GOLD if primary or selected else EDGE, 12)
        self.text(label, *rect.center, 21, INK if (primary or selected) and enabled else CREAM if enabled else (86, 110, 116), "center")
        self.buttons.append((key, rect, enabled))

    def make_background(self):
        surface = pg.Surface((W, H))
        for y in range(H):
            t = y / H
            pg.draw.line(surface, (int(13 + 8 * t), int(33 + 17 * t), int(42 + 12 * t)), (0, y), (W, y))
        pg.draw.ellipse(surface, (29, 68, 72), (-100, 210, 1640, 630), 1)
        pg.draw.ellipse(surface, (28, 61, 68), (-45, 247, 1530, 565), 1)
        rng = random.Random(6)
        for _ in range(65):
            x, y = rng.randrange(W), rng.randrange(110, H - 70)
            pg.draw.circle(surface, (43, 70, 74), (x, y), 1)
        return surface

    def suit(self, suit, x, y, size, color):
        x, y, size = int(x), int(y), int(size)
        h = size // 2
        if suit == 3:  # 方片
            pg.draw.polygon(self.canvas, color, [(x, y-h), (x+h, y), (x, y+h), (x-h, y)])
        elif suit == 1:  # 红心
            pg.draw.circle(self.canvas, color, (x-size//4, y-size//5), size//3)
            pg.draw.circle(self.canvas, color, (x+size//4, y-size//5), size//3)
            pg.draw.polygon(self.canvas, color, [(x-h, y), (x+h, y), (x, y+h)])
        elif suit == 0:  # 黑桃
            pg.draw.polygon(self.canvas, color, [(x, y-h), (x-h, y+size//8), (x+h, y+size//8)])
            pg.draw.circle(self.canvas, color, (x-size//4, y+size//8), size//3)
            pg.draw.circle(self.canvas, color, (x+size//4, y+size//8), size//3)
            pg.draw.polygon(self.canvas, color, [(x, y), (x-size//5, y+h+2), (x+size//5, y+h+2)])
        else:
            for dx, dy in ((0, -size//4), (-size//4, size//8), (size//4, size//8)):
                pg.draw.circle(self.canvas, color, (x+dx, y+dy), size//3)
            pg.draw.polygon(self.canvas, color, [(x, y), (x-size//5, y+h+2), (x+size//5, y+h+2)])

    def card(self, card, x, y, width=82, height=122, selected=False, back=False):
        rect = pg.Rect(round(x), round(y), width, height)
        pg.draw.rect(self.canvas, (8, 24, 29), rect.move(2, 5), border_radius=9)
        if back:
            self.panel(rect, (34, 70, 80), (83, 122, 125), 9)
            pg.draw.rect(self.canvas, (63, 102, 111), rect.inflate(-10, -10), 1, border_radius=6)
            cx, cy = rect.center
            pg.draw.polygon(self.canvas, GOLD, [(cx, cy-12), (cx+8, cy), (cx, cy+12), (cx-8, cy)], 1)
            return rect
        self.panel(rect, (255, 242, 208) if selected else CREAM, GOLD if selected else (205, 207, 190), 9)
        if selected:
            pg.draw.rect(self.canvas, GOLD, rect, 3, border_radius=9)
        r = rank(card)
        color = RED if card == 54 or (card <= 52 and (card-1) % 4 in (1, 3)) else (30, 54, 62)
        if r >= 16:
            fs = max(13, int(width * .27))
            self.text("大" if r == 17 else "小", rect.x+7, rect.y+5, fs, color)
            self.text("王", rect.x+7, rect.y+fs+5, fs, color)
            if width >= 65:
                self.text("JOKER", rect.centerx, rect.bottom-16, 11, color, "center")
        else:
            fs = max(15, int(width * .33))
            self.text(RANK_TEXT[r], rect.x+7, rect.y+3, fs, color)
            self.suit((card-1) % 4, rect.x+15, rect.y+fs+18, max(12, width//5), color)
            if width >= 65:
                self.suit((card-1) % 4, rect.centerx+9, rect.centery+20, width//3, color)
        return rect

    def notify(self, message, duration=3):
        self.toast, self.toast_until = message, self.now + duration

    def cancel_pending(self):
        self.epoch += 1
        if self.pending:
            self.pending[0].cancel()
        self.pending = None

    def start(self, seed=None):
        self.cancel_pending()
        self.game = Game(self.difficulty, seed)
        self.mode, self.modal = "game", None
        self.selected.clear()
        self.hint_revision = -1
        self.bomb_until = self.over_at = 0
        self.toast_until = 0
        self.next_ai = self.now + .8

    def changed(self, old_bomb, result):
        ok, message = result
        if not ok:
            self.notify(message)
            return
        self.selected.intersection_update(self.game.hands[0])
        self.hint_revision = -1
        self.toast_until = 0
        self.next_ai = self.now + .85
        if self.game.bomb_serial != old_bomb:
            self.bomb_text = self.game.last_bomb
            self.bomb_until = self.now + 1.35
            self.next_ai = self.bomb_until
        if self.game.phase == "over":
            self.over_at = max(self.now + .45, self.bomb_until)

    def act(self, key):
        if key == "sound":
            self.audio.toggle()
            return
        self.audio.play("button")
        if key == "rules":
            self.modal = "rules"
        elif key == "close_modal":
            self.modal = None
        elif key == "menu":
            self.mode, self.modal = "menu", None
        elif key == "resume":
            self.mode = "game"
        elif key.startswith("difficulty_"):
            self.difficulty = int(key[-1])
        elif key == "start":
            self.start()
        elif key == "again":
            self.difficulty = self.game.difficulty
            self.start()
        elif key == "clear":
            self.selected.clear()
        elif self.game and self.game.turn == 0:
            g = self.game
            old_bomb = g.bomb_serial
            if key == "play":
                self.changed(old_bomb, g.play(0, [c for c in g.hands[0] if c in self.selected]))
            elif key == "pass":
                result = g.pass_turn(0)
                if result[0]:
                    self.selected.clear()
                self.changed(old_bomb, result)
            elif key in ("yes", "no"):
                self.changed(old_bomb, g.bid(0, key == "yes"))
            elif key == "hint" and g.phase == "play":
                if self.hint_revision == g.revision:
                    self.apply_hint()
                elif self.pending is None:
                    view = replace(g.view(0), difficulty=2)
                    self.pending = (self.executor.submit(ai.ranked_moves, view), self.epoch, g.revision, "hint", 0, self.now)
                    self.notify("正在整理可出的牌…", 2)

    def apply_hint(self):
        if not self.hint_moves:
            self.selected.clear()
            self.notify("没有能压过的牌，可以点击“不出”")
            return
        move = self.hint_moves[self.hint_index % len(self.hint_moves)]
        self.hint_index += 1
        self.selected = set(cards_for(self.game.hands[0], move.c))
        self.notify(f"{move.label} · 再点提示可换一组", 2)

    def update(self):
        self.now = time.monotonic()
        if self.mode != "game" or self.modal or not self.game:
            return
        g = self.game
        if self.pending:
            future, epoch, revision, task, seat, not_before = self.pending
            if future.done() and self.now >= not_before:
                self.pending = None
                if epoch != self.epoch or revision != g.revision:
                    return
                try:
                    answer = future.result()
                except Exception:
                    logging.exception("AI/提示计算异常")
                    self.notify("计算遇到问题，已切换为基础出牌；详情见日志。", 5)
                    if task == "hint":
                        answer = legal_moves(counts(g.hands[0]), g.last)
                    elif task == "bid":
                        answer = False
                    else:
                        choices = legal_moves(counts(g.hands[seat]), g.last)
                        answer = cards_for(g.hands[seat], choices[0].c) if choices else None
                if task == "hint":
                    self.hint_revision, self.hint_index, self.hint_moves = revision, 0, answer
                    self.apply_hint()
                else:
                    result = g.bid(seat, answer) if task == "bid" else g.play(seat, answer) if answer else g.pass_turn(seat)
                    # 理论上不可达；若策略返回非法动作，记录并使用已校验候选恢复。
                    if not result[0]:
                        logging.error("AI 非法动作：%s", result[1])
                        choices = legal_moves(counts(g.hands[seat]), g.last)
                        result = g.play(seat, cards_for(g.hands[seat], choices[0].c)) if choices else g.pass_turn(seat)
                    self.changed(self.last_seen_bomb, result)
        if self.pending or self.now < self.next_ai or g.phase == "over":
            return
        if g.phase == "redeal":
            g.deal()
            self.selected.clear()
            self.hint_revision = -1
            self.next_ai = self.now + .9
            return
        if g.turn == 0:
            return
        task = "play" if g.phase == "play" else "bid"
        view = g.view(g.turn)
        rng = random.Random(self.decision_rng.getrandbits(64))
        future = self.executor.submit(ai.choose if task == "play" else ai.bid, view, rng)
        self.last_seen_bomb = g.bomb_serial
        self.pending = (future, self.epoch, g.revision, task, g.turn, self.now + .3)

    def menu(self):
        self.button("sound", self.audio.label, (1078, 29, 145, 44), enabled=self.audio.available)
        self.button("rules", "玩法说明", (1240, 29, 140, 44))
        self.text("三人经典斗地主", 355, 310, 48, CREAM, "center")
        for i, card in enumerate((49, 50, 53, 54)):
            self.card(card, 150+i*95, 445 + (0 if i in (1, 2) else 22), 108, 157)
        self.text("选择难度", 820, 178, 24)
        descriptions = ("轻松熟悉规则，允许电脑犯些小错", "合理顺牌、保留炸弹，也会配合队友", "公开记牌、主动拦截，增加残局推算")
        for i, (name, desc) in enumerate(zip(DIFFICULTIES, descriptions), 1):
            rect = pg.Rect(810, 232 + (i-1)*120, 500, 101)
            chosen = self.difficulty == i
            self.panel(rect, (36, 66, 69) if chosen else PANEL, GOLD if chosen else EDGE)
            self.text(f"0{i}", rect.x+24, rect.y+29, 25, GOLD if chosen else MUTED)
            self.text(name, rect.x+88, rect.y+16, 26)
            self.text(desc, rect.x+88, rect.y+59, 17, MUTED)
            pg.draw.circle(self.canvas, GOLD if chosen else EDGE, (rect.right-28, rect.y+32), 7, 0 if chosen else 2)
            self.buttons.append((f"difficulty_{i}", rect, True))
        self.button("start", "开始新的一局  →", (810, 634, 500, 61), True)
        if self.game and self.game.phase != "over":
            self.button("resume", "继续当前对局", (810, 714, 500, 48))
            self.text("开始新局会结束当前对局", 1060, 783, 16, MUTED, "center")
        self.text(f"作者：{AUTHOR}  ·  Python {platform.python_version()}", 720, 860, 15, MUTED, "center")

    def role(self, seat):
        if self.game.phase not in ("play", "over"):
            return "待定"
        return "地主" if seat == self.game.lord else "农民"

    def player(self, seat, x, y):
        g = self.game
        active = g.turn == seat and g.phase not in ("over", "redeal")
        self.panel((x, y, 188, 92), PANEL, GOLD if active else EDGE, 15)
        pg.draw.circle(self.canvas, (64, 91, 92), (x+35, y+37), 23)
        self.text(str(seat), x+35, y+36, 22, GOLD, "center")
        self.text(NAMES[seat], x+71, y+12, 23)
        self.text(self.role(seat), x+73, y+48, 17, GOLD if seat == g.lord else TEAL)
        remaining = len(g.hands[seat])
        self.text(f"剩 {remaining} 张", x+94, y+121, 24, GOLD if remaining <= 2 else CREAM, "center")
        if remaining <= 2 and remaining > 0 and g.phase in ("play", "over"):
            self.text("报单！" if remaining == 1 else "报双！", x+94, y+157, 18, GOLD, "center")
        for j in range(min(remaining, 5)):
            self.card(None, x+46+j*15, y+184, 40, 59, back=True)

    def played(self, seat, cx, y, maximum=405):
        g = self.game
        action = g.shown.get(seat)
        if g.phase in ("call", "rob", "final_rob"):
            self.text(g.bid_texts[seat], cx, y+35, 26, GOLD, "center")
        elif action:
            self.text(action.move.label if action.move else "不出", cx, y-18, 18, MUTED, "center")
            if action.cards:
                cards = action.cards
                # 两侧长飞机分两行，避免相邻牌遮掉点数；自己的展示区更宽。
                compact = seat != 0 and len(cards) > 11
                rows = [cards[i:i+10] for i in range(0, len(cards), 10)] if compact else [cards]
                width, height = (44, 62) if compact else (57, 82)
                for row, group in enumerate(rows):
                    step = min(43, (maximum-width) / max(1, len(group)-1))
                    start = cx - (width + (len(group)-1)*step) / 2
                    for i, card in enumerate(group):
                        self.card(card, start+i*step, y+row*(height+6), width, height)
        elif seat == g.turn and g.phase == "play" and seat != 0:
            dots = "." * (int(self.now*2) % 3 + 1)
            self.text("思考中"+dots, cx, y+28, 20, MUTED, "center")

    def game_table(self):
        g = self.game
        self.text("三人经典斗地主", 42, 24, 27)
        self.text(f"单人 · {DIFFICULTIES[g.difficulty-1]}   /   第 {g.round} 回合", 44, 69, 18, MUTED)
        self.panel((346, 28, 398, 61), PANEL, EDGE, 13)
        if g.phase == "redeal":
            status = "无人叫地主，即将重新发牌"
        elif g.phase == "over":
            status = "本局结束"
        else:
            action = "出牌" if g.phase == "play" else "叫地主" if g.phase == "call" else "抢地主"
            status = f"{NAMES[g.turn]}{(' · 最后抢牌' if g.phase == 'final_rob' else ' · ' + action)}"
        self.text(status, 545, 57, 22, GOLD if g.turn == 0 else CREAM, "center")
        self.text("底牌", 785, 32, 15, MUTED)
        for i, card in enumerate(g.bottom):
            self.card(card, 836+i*45, 21, 38, 57, back=g.phase not in ("play", "over"))
        self.text(f"×{g.multiplier}", 1005, 18, 31, GOLD)
        self.text(f"手牌 {len(g.hands[0])} 张", 1005, 61, 16, MUTED)
        self.button("sound", self.audio.label, (1130, 29, 110, 44), enabled=self.audio.available)
        self.button("rules", "规则", (1250, 29, 65, 44))
        self.button("menu", "菜单", (1325, 29, 70, 44))
        pg.draw.line(self.canvas, EDGE, (42, 112), (1398, 112))
        self.player(2, 44, 211)
        self.player(1, 1208, 211)
        self.text("斗地主", 720, 220, 42, (61, 96, 98), "center")
        self.text("你 → 右家 → 左家", 720, 271, 16, MUTED, "center")
        self.played(2, 450, 312, 390)
        self.played(1, 990, 312, 390)
        self.played(0, 720, 450, 690)
        human_turn = g.turn == 0 and g.phase not in ("over", "redeal")
        if g.phase in ("call", "rob", "final_rob"):
            yes = "叫地主" if g.phase == "call" else "抢地主"
            no = "不叫" if g.phase == "call" else "不抢"
            self.button("no", no, (506, 561, 190, 55), enabled=human_turn)
            self.button("yes", yes, (720, 561, 210, 55), True, human_turn)
        elif g.phase == "play":
            self.button("hint", "提示  H", (329, 561, 166, 55), enabled=human_turn)
            self.button("clear", "清空选牌", (515, 561, 166, 55), enabled=bool(self.selected))
            self.button("pass", "不出  P", (701, 561, 166, 55), enabled=human_turn and g.last is not None)
            self.button("play", "出牌  Enter", (887, 561, 224, 55), True, human_turn)
        elif g.phase == "redeal":
            self.text("三家均不叫，正在洗牌…", 720, 585, 23, GOLD, "center")
        if self.now < self.toast_until:
            self.text(self.toast, 720, 641, 20, GOLD, "center")
        elif self.selected and g.phase == "play":
            m = classify(counts(self.selected))
            status = f"已选 {len(self.selected)} 张 · " + (m.label if m else "尚未组成合法牌型")
            if m and not beats(m, g.last):
                status += " · 不能压过上一手"
            self.text(status, 720, 641, 18, GOLD, "center")
        else:
            self.text("点击手牌选中，再次点击取消" if human_turn else "等待对手行动 · 可以提前选牌", 720, 641, 17, MUTED, "center")
        hand = g.hands[0]
        width, height = 83, 124
        step = min(65, 1230 / max(1, len(hand)-1))
        start = (W-width-step*(len(hand)-1))/2
        for i, card in enumerate(hand):
            selected = card in self.selected
            rect = self.card(card, start+i*step, 702-(24 if selected else 0), width, height, selected)
            self.card_hits.append((card, rect))
        self.text("你", 55, 852, 23, CREAM, "midleft")
        self.text(self.role(0), 102, 852, 20, GOLD if g.lord == 0 else TEAL, "midleft")
        self.text(f"{len(hand)} 张", 173, 852, 18, MUTED, "midleft")
        self.text("H 提示   ·   P 不出   ·   Enter 出牌   ·   右键清空", 1378, 855, 16, MUTED, "midright")

    def shade(self, alpha=175):
        overlay = pg.Surface((W, H), pg.SRCALPHA)
        overlay.fill((3, 13, 19, alpha))
        self.canvas.blit(overlay, (0, 0))

    def rules(self):
        self.shade(215)
        self.buttons.clear()
        self.card_hits.clear()
        self.panel((170, 75, 1100, 750), (22, 47, 55), EDGE, 23)
        self.text("玩法说明", 214, 105, 32, GOLD)
        self.button("close_modal", "返回", (1110, 100, 110, 46))
        lines = [
            "叫抢地主：每家 17 张，留 3 张底牌。随机首叫，全部不叫则重新发牌。",
            "有人叫后，另两家各抢一次；若有人抢，首叫者可最后抢一次。每抢一次 ×2。",
            "地主获得底牌并先出。顺序：你 → 右家 → 左家。连续两家不出后重新领出。",
            "牌型：单张、对子、三张、三带一、三带二；顺子至少 5 张，连对至少 3 对。",
            "飞机：至少两组连续三张，可不带牌、每组带一张，或每组带一个不同点数的对子。",
            "四带二：四张带两张（可以是一对），或带两个不同点数的对子；它不算炸弹。",
            "连续牌不能含 2 或王。飞机带牌不能与主体同点；单翅每点数最多两张。",
            "飞机单翅、四带二单不可同时带大小王；一个炸弹不可拆作两对翅膀。",
            "普通牌比较相同牌型、相同张数的主体点数。大小：3…10、J、Q、K、A、2、小王、大王。",
            "炸弹压普通牌；大炸弹压小炸弹；王炸最大。炸弹、王炸均 ×2。首出不能“不出”。",
            "一方出完即结束。任一农民出完，农民队共同获胜。地主胜且农民未出牌为春天 ×2。",
            "农民胜且地主仅出过一手为反春天 ×2。地主得失 2 倍分，农民各 1 倍分。",
            "点击选牌 / 取消。H 提示（可连续换组），Enter 出牌，P 不出，右键清空，Esc 返回。",
            "困难 AI 根据公开信息推算未知牌，没有透视；受抽样与思考预算限制，不保证必胜。",
        ]
        for i, line in enumerate(lines):
            self.text(line, 214, 177+i*40, 18, CREAM if i % 2 == 0 else MUTED)
        self.text("结算后按空格重新开始同难度；菜单可更换难度。", 214, 765, 19, GOLD)

    def settlement(self):
        g = self.game
        self.shade(205)
        self.buttons.clear()
        self.card_hits.clear()
        self.panel((380, 184, 680, 495), (24, 51, 58), GOLD, 24)
        human_won = same_team(0, g.winner, g.lord)
        self.text("赢得漂亮" if human_won else "下一局，再来", 720, 226, 21, MUTED, "center")
        self.text("地主获胜" if g.winner == g.lord else "农民获胜", 720, 292, 48, GOLD, "center")
        self.text(f"{NAMES[g.winner]}率先出完手牌", 720, 352, 22, CREAM, "center")
        self.text(f"最终倍数 ×{g.multiplier}" + (f"   ·   {g.spring}" if g.spring else ""), 720, 396, 23, TEAL, "center")
        scores = g.scores()
        for p, x in ((0, 525), (1, 720), (2, 915)):
            self.text(NAMES[p], x, 451, 18, MUTED, "center")
            self.text(f"{scores[p]:+d}", x, 495, 33, GOLD if scores[p] > 0 else CREAM, "center")
        self.button("menu", "更换难度", (450, 551, 225, 57))
        self.button("again", "再来一局", (701, 551, 286, 57), True)
        self.text("按空格键重新开始", 720, 642, 18, MUTED, "center")

    def render(self):
        self.buttons.clear()
        self.card_hits.clear()
        self.canvas.blit(self.background, (0, 0))
        if self.mode == "menu":
            self.menu()
        else:
            self.game_table()
            if self.now < self.bomb_until:
                self.panel((515, 175, 410, 114), (60, 49, 39), GOLD, 20)
                self.text(self.bomb_text, 720, 228, 49, GOLD, "center")
            if self.game.phase == "over" and self.now >= self.over_at:
                self.settlement()
        if self.modal == "rules":
            self.rules()
        sw, sh = self.screen.get_size()
        scale = min(sw / W, sh / H)
        dw, dh = max(1, round(W*scale)), max(1, round(H*scale))
        x, y = (sw-dw)//2, (sh-dh)//2
        # 震动只作用于显示；动画期间不接受牌桌点击，避免命中框错位。
        if self.mode == "game" and not self.modal and self.bomb_until-self.now > .75:
            amp = 6 * min(1, (self.bomb_until-self.now-.75)/.6)
            x += round(math.sin(self.now*91)*amp)
            y += round(math.cos(self.now*77)*amp)
        self.viewport = pg.Rect(x, y, dw, dh)
        self.screen.fill((7, 19, 25))
        self.screen.blit(pg.transform.smoothscale(self.canvas, (dw, dh)), (x, y))
        pg.display.flip()

    def mouse_logical(self, pos):
        v = self.viewport
        return ((pos[0]-v.x)*W/v.w, (pos[1]-v.y)*H/v.h)

    def handle(self, event):
        if event.type == pg.QUIT:
            self.running = False
        elif event.type == pg.VIDEORESIZE:
            self.screen = pg.display.set_mode((max(720, event.w), max(450, event.h)), pg.RESIZABLE)
        elif event.type == pg.MOUSEMOTION:
            self.mouse = self.mouse_logical(event.pos)
        elif event.type == pg.KEYDOWN:
            if event.key == pg.K_ESCAPE:
                if self.modal:
                    self.modal = None
                elif self.mode == "game":
                    self.mode = "menu"
                elif self.game and self.game.phase != "over":
                    self.mode = "game"
            elif not self.modal and self.mode == "game":
                g = self.game
                if g.phase == "over":
                    if event.key == pg.K_SPACE and self.now >= self.over_at:
                        self.act("again")
                elif self.now >= self.bomb_until:
                    mapping = {pg.K_RETURN: "play", pg.K_KP_ENTER: "play", pg.K_h: "hint", pg.K_p: "pass"}
                    if event.key in mapping and g.phase == "play":
                        self.act(mapping[event.key])
        elif event.type == pg.MOUSEBUTTONDOWN:
            self.mouse = self.mouse_logical(event.pos)
            if self.mode == "game" and self.now < self.bomb_until and not self.modal:
                return
            if event.button == 3 and self.mode == "game" and not self.modal:
                if self.selected:
                    self.audio.play("card")
                self.selected.clear()
            if event.button != 1:
                return
            for key, rect, enabled in reversed(self.buttons):
                if rect.collidepoint(self.mouse):
                    if enabled:
                        self.act(key)
                    return
            if self.mode == "game" and not self.modal and self.game.phase != "over":
                for card, rect in reversed(self.card_hits):
                    if rect.collidepoint(self.mouse):
                        self.audio.play("card")
                        if card in self.selected:
                            self.selected.remove(card)
                        else:
                            self.selected.add(card)
                        return

    def run(self):
        while self.running:
            self.now = time.monotonic()
            # 刷新命中框后处理事件；新局不会沿用上一屏的按钮坐标。
            self.render()
            for event in pg.event.get():
                self.handle(event)
                self.render()
            self.update()
            self.clock.tick(60)

    def close(self):
        self.cancel_pending()
        self.executor.shutdown(wait=True, cancel_futures=True)
        pg.quit()
