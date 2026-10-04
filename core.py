"""三人经典斗地主：纯 Python 规则和状态机，不依赖图形库。席位：你 0 → 右 1 → 左 2。"""
from dataclasses import dataclass
from functools import lru_cache
import random

LABELS = dict(single="单张", pair="对子", triple="三张", triple1="三带一",
              triple2="三带二", straight="顺子", pairs="连对", plane="飞机",
              plane1="飞机带单", plane2="飞机带对", four1="四带二单",
              four2="四带两对", bomb="炸弹", rocket="王炸")
DIFFICULTIES = ("新手", "普通", "困难")
RANK_TEXT = {**{r: str(r) for r in range(3, 11)}, 11: "J", 12: "Q",
             13: "K", 14: "A", 15: "2", 16: "小王", 17: "大王"}
ZERO = (0,) * 15


def rank(card):
    return (card - 1) // 4 + 3 if card <= 52 else card - 37


def counts(cards):
    c = [0] * 15
    for card in cards:
        c[rank(card) - 3] += 1
    return tuple(c)


def sorted_hand(cards):
    return sorted(cards, key=lambda c: (rank(c), c), reverse=True)


def subtract(a, b):
    return tuple(x - y for x, y in zip(a, b))


def same_team(a, b, lord):
    return (a == lord) == (b == lord)


@dataclass(frozen=True)
class Move:
    kind: str
    rank: int
    n: int
    length: int = 1
    c: tuple = ZERO

    @property
    def label(self):
        return LABELS[self.kind]


def classify(c):
    """c 为 3..大王的 15 项张数。拒绝不存在的牌张组合。"""
    if len(c) != 15 or any(type(v) is not int or v < 0 or v > (4 if i < 13 else 1)
                           for i, v in enumerate(c)):
        return None
    n = sum(c)
    groups = [i for i, v in enumerate(c) if v]
    if not groups:
        return None
    lo, hi = groups[0], groups[-1]

    def desc(kind, top, length=1):
        return Move(kind, top + 3, n, length, tuple(c))

    if n == 2 and c[13] == c[14] == 1:
        return desc("rocket", 14)
    if len(groups) == 1:
        return desc(("single", "pair", "triple", "bomb")[n - 1], hi)
    for r in range(13):
        if c[r] == 3 and n in (4, 5) and any(i != r and c[i] == n - 3 for i in groups):
            return desc("triple1" if n == 4 else "triple2", r)
        if c[r] == 4 and n in (6, 8):
            rest = [c[i] for i in groups if i != r]
            if n == 6 and max(rest) <= 2 and not (c[13] and c[14]):
                return desc("four1", r)
            if n == 8 and rest == [2, 2]:
                return desc("four2", r)
    if hi <= 11 and hi - lo + 1 == len(groups):
        for unit, minimum, kind in ((1, 5, "straight"), (2, 3, "pairs"), (3, 2, "plane")):
            if len(groups) >= minimum and all(c[i] == unit for i in groups):
                return desc(kind, hi, len(groups))
    for unit in (4, 5):
        length = n // unit
        if n % unit or length < 2:
            continue
        for top in range(11, length - 2, -1):
            body = range(top - length + 1, top + 1)
            if not all(c[i] == 3 for i in body):
                continue
            rest = [c[i] for i in groups if i not in body]
            if unit == 4 and sum(rest) == length and max(rest, default=0) <= 2 and not (c[13] and c[14]):
                return desc("plane1", top, length)
            if unit == 5 and len(rest) == length and all(v == 2 for v in rest):
                return desc("plane2", top, length)
    return None


def beats(move, target):
    if move is None:
        return False
    if target is None:
        return True
    if target.kind == "rocket":
        return False
    if move.kind == "rocket" or (move.kind == "bomb" and target.kind != "bomb"):
        return True
    return (move.kind, move.n, move.length) == (target.kind, target.n, target.length) and move.rank > target.rank


@lru_cache(maxsize=4096)
def all_moves(c):
    """按点数组合枚举（不枚举等价花色），包括拆牌；缓存结果不可变。"""
    found = {}

    def add(m):
        key = tuple(m)
        if key not in found:
            move = classify(key)
            if move:
                found[key] = move

    def attach(base, need, unit):
        eligible = [(i, min(c[i] // unit, 2 if unit == 1 else 1))
                    for i in range(15) if not base[i] and c[i] >= unit]
        suffix = [0] * (len(eligible) + 1)
        for j in range(len(eligible) - 1, -1, -1):
            suffix[j] = suffix[j + 1] + eligible[j][1]
        m = base[:]

        def walk(j, left):
            if left == 0:
                add(m)
                return
            if j == len(eligible) or suffix[j] < left:
                return
            i, available = eligible[j]
            for take in range(min(left, available) + 1):
                m[i] = take * unit
                walk(j + 1, left - take)
            m[i] = 0
        walk(0, need)

    for r, number in enumerate(c):
        for n in range(1, number + 1):
            m = [0] * 15
            m[r] = n
            add(m)
        if number >= 3:
            for t, available in enumerate(c):
                if t == r:
                    continue
                for n in range(1, min(2, available) + 1):
                    m = [0] * 15
                    m[r], m[t] = 3, n
                    add(m)
        if number == 4:
            m = [0] * 15
            m[r] = 4
            attach(m, 2, 1)
            attach(m, 2, 2)
    if c[13] and c[14]:
        add([0] * 13 + [1, 1])
    for unit, minimum in ((1, 5), (2, 3), (3, 2)):
        for lo in range(12):
            m = [0] * 15
            for hi in range(lo, 12):
                if c[hi] < unit:
                    break
                m[hi] = unit
                length = hi - lo + 1
                if length >= minimum:
                    add(m)
                    if unit == 3:
                        if sum(c) >= length * 4:
                            attach(m, length, 1)
                        if sum(c) >= length * 5:
                            attach(m, length, 2)
    return tuple(sorted(found.values(), key=lambda m: (-m.n, m.rank, m.kind, m.c)))


def legal_moves(c, target=None):
    return [m for m in all_moves(tuple(c)) if beats(m, target)]


def cards_for(hand, c):
    need = list(c)
    out = []
    for card in hand:
        r = rank(card) - 3
        if need[r]:
            out.append(card)
            need[r] -= 1
    if any(need):
        raise ValueError("手牌不足")
    return out


@dataclass(frozen=True)
class Action:
    seat: int
    cards: tuple = ()
    move: Move | None = None


@dataclass(frozen=True)
class View:
    """只含自己的牌和公开信息；AI 永远拿不到 Game 或另两家真实手牌。"""
    seat: int
    hand: tuple
    remaining: tuple
    lord: int | None
    difficulty: int
    last: Move | None
    last_seat: int | None
    passes: int
    history: tuple
    bottom: tuple
    phase: str


class Game:
    def __init__(self, difficulty=2, seed=None):
        if difficulty not in (1, 2, 3):
            raise ValueError("难度必须为 1、2 或 3")
        self.difficulty = difficulty
        self.random = random.Random(seed)
        self.deal_number = self.revision = 0
        self.deal()

    def deal(self):
        self.deal_number += 1
        self.revision += 1
        deck = list(range(1, 55))
        self.random.shuffle(deck)
        self.hands = [sorted_hand(deck[p:51:3]) for p in range(3)]
        self.bottom = deck[51:]
        self.phase = "call"
        self.turn = self.random.randrange(3)
        self.caller = self.lord = self.winner = self.spring = None
        self.call_steps = self.rob_steps = self.passes = self.actions = 0
        self.round = self.multiplier = 1
        self.last = self.last_seat = None
        self.history = []
        self.shown = {}
        self.plays = [0, 0, 0]
        self.bid_texts = ["等待", "等待", "等待"]
        self.bomb_serial = 0
        self.last_bomb = ""

    def finish_bid(self):
        self.hands[self.lord] = sorted_hand(self.hands[self.lord] + self.bottom)
        self.turn, self.phase = self.lord, "play"
        self.bid_texts = ["", "", ""]

    def bid(self, seat, yes):
        if seat != self.turn or self.phase not in ("call", "rob", "final_rob"):
            return False, "现在不是你的叫抢回合"
        self.revision += 1
        if self.phase == "call":
            self.call_steps += 1
            self.bid_texts[seat] = "叫地主" if yes else "不叫"
            if yes:
                self.caller = self.lord = seat
                self.phase, self.rob_steps = "rob", 0
                self.turn = (seat + 1) % 3
            elif self.call_steps == 3:
                self.phase, self.turn = "redeal", None
            else:
                self.turn = (seat + 1) % 3
        elif self.phase == "rob":
            self.rob_steps += 1
            self.bid_texts[seat] = "抢地主" if yes else "不抢"
            if yes:
                self.lord = seat
                self.multiplier *= 2
            if self.rob_steps == 2:
                if self.lord != self.caller:
                    self.phase, self.turn = "final_rob", self.caller
                else:
                    self.finish_bid()
            else:
                self.turn = (seat + 1) % 3
        else:
            self.bid_texts[seat] = "抢地主" if yes else "不抢"
            if yes:
                self.lord = seat
                self.multiplier *= 2
            self.finish_bid()
        return True, ""

    def play(self, seat, cards):
        if self.phase != "play" or seat != self.turn:
            return False, "请等待你的回合"
        if not cards:
            return False, "请先选择要出的牌"
        if len(set(cards)) != len(cards) or not set(cards) <= set(self.hands[seat]):
            return False, "选牌已变化，请重新选择"
        move = classify(counts(cards))
        if not move:
            return False, "牌型不符合规则，请调整选牌"
        if not beats(move, self.last):
            return False, "请出同牌型、同张数且更大的牌，或炸弹／王炸"
        used = set(cards)
        self.hands[seat] = [c for c in self.hands[seat] if c not in used]
        self.last, self.last_seat, self.passes = move, seat, 0
        self.plays[seat] += 1
        self.actions += 1
        action = Action(seat, tuple(sorted_hand(cards)), move)
        self.shown[seat] = action
        self.history.append(action)
        if move.kind in ("bomb", "rocket"):
            self.multiplier *= 2
            self.bomb_serial += 1
            self.last_bomb = move.label + "！"
        self.revision += 1
        if not self.hands[seat]:
            self.phase, self.winner = "over", seat
            if seat == self.lord and all(self.plays[p] == 0 for p in range(3) if p != self.lord):
                self.spring = "春天"
            elif seat != self.lord and self.plays[self.lord] == 1:
                self.spring = "反春天"
            if self.spring:
                self.multiplier *= 2
        else:
            self.turn = (seat + 1) % 3
            self.shown.pop(self.turn, None)
        return True, ""

    def pass_turn(self, seat):
        if self.phase != "play" or seat != self.turn:
            return False, "请等待你的回合"
        if self.last is None:
            return False, "你是本轮首出，必须出牌"
        action = Action(seat)
        self.shown[seat] = action
        self.history.append(action)
        self.actions += 1
        self.passes += 1
        self.turn = (seat + 1) % 3
        self.revision += 1
        if self.passes == 2:
            self.last = self.last_seat = None
            self.passes = 0
            self.round += 1
            self.shown.clear()
        else:
            self.shown.pop(self.turn, None)
        return True, ""

    def view(self, seat):
        return View(seat, tuple(self.hands[seat]), tuple(map(len, self.hands)),
                    self.lord, self.difficulty, self.last, self.last_seat,
                    self.passes, tuple(self.history),
                    tuple(self.bottom) if self.phase in ("play", "over") else (), self.phase)

    def scores(self):
        if self.phase != "over":
            return (0, 0, 0)
        landlord_won = self.winner == self.lord
        return tuple((2 if p == self.lord else 1) * self.multiplier *
                     (1 if (p == self.lord) == landlord_won else -1) for p in range(3))
