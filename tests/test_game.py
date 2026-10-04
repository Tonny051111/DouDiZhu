"""规则、状态机、公平信息边界和完整对局回归。无需图形依赖。"""
import copy
from itertools import product
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ai
from core import Game, counts, classify, beats, legal_moves, cards_for, same_team


def c(*ranks):
    return tuple(ranks.count(r) for r in range(3, 18))


class RulesTest(unittest.TestCase):
    def test_all_kinds(self):
        examples = {
            "single": (3,), "pair": (4, 4), "triple": (5, 5, 5),
            "triple1": (6, 6, 6, 3), "triple2": (7, 7, 7, 4, 4),
            "straight": (10, 11, 12, 13, 14), "pairs": (3, 3, 4, 4, 5, 5),
            "plane": (3, 3, 3, 4, 4, 4), "plane1": (3, 3, 3, 4, 4, 4, 6, 6),
            "plane2": (3, 3, 3, 4, 4, 4, 6, 6, 8, 8),
            "four1": (8, 8, 8, 8, 5, 5), "four2": (8, 8, 8, 8, 5, 5, 6, 6),
            "bomb": (9, 9, 9, 9), "rocket": (16, 17),
        }
        for kind, ranks in examples.items():
            with self.subTest(kind=kind):
                self.assertEqual(classify(c(*ranks)).kind, kind)

    def test_illegal(self):
        for ranks in ((), (3, 4), (3, 3, 4, 4), (11, 12, 13, 14, 15),
                      (14, 14, 14, 15, 15, 15), (16, 16), (3, 3, 3, 3, 3),
                      (3, 3, 3, 4, 4, 4, 16, 17), (3, 3, 3, 4, 4, 4, 5, 5, 5, 8, 8, 8),
                      (3, 3, 3, 3, 4, 4, 4, 5), (8, 8, 8, 8, 5, 5, 5, 5)):
            with self.subTest(ranks=ranks):
                self.assertIsNone(classify(c(*ranks)))

    def test_comparison(self):
        pairs = [((3, 3, 3, 3), (17,), True), ((16, 17), (15, 15, 15, 15), True),
                 ((4, 4), (3,), False), ((3, 3), (3, 3), False),
                 ((4, 5, 6, 7, 8, 9), (3, 4, 5, 6, 7), False),
                 ((4, 4, 4, 3), (3, 3, 3, 17), True),
                 ((15, 15, 15, 15), (16, 17), False)]
        for a, b, expected in pairs:
            self.assertEqual(beats(classify(c(*a)), classify(c(*b))), expected)

    def test_generator_exhaustive_subsets(self):
        hands = [(3, 3, 3, 4, 4, 4, 5, 5, 6, 6, 16, 17),
                 (3, 3, 3, 3, 4, 4, 5, 5, 6, 7, 8, 9),
                 tuple(range(3, 15)),
                 (3, 3, 3, 4, 4, 4, 5, 5, 5, 6, 6, 6, 7, 7, 8, 8)]
        for ranks in hands:
            full = c(*ranks)
            generated = {m.c for m in legal_moves(full)}
            expected = {sub for sub in product(*(range(n+1) for n in full)) if classify(sub)}
            self.assertEqual(generated, expected)


class StateTest(unittest.TestCase):
    def play_game(self, seed=1, difficulty=2):
        g = Game(difficulty, seed)
        g.bid(g.turn, True)
        g.bid(g.turn, False)
        g.bid(g.turn, False)
        return g

    def test_deal(self):
        g = Game(2, 7)
        self.assertEqual([len(h) for h in g.hands], [17, 17, 17])
        cards = sum(g.hands, []) + g.bottom
        self.assertEqual(sorted(cards), list(range(1, 55)))
        self.assertEqual(g.view(0).bottom, ())
        g.bid(g.turn, True)
        g.bid(g.turn, False)
        g.bid(g.turn, False)
        self.assertEqual(len(g.hands[g.lord]), 20)
        self.assertEqual(len(g.view(0).bottom), 3)

    def test_bid_tree(self):
        for mask in range(64):
            g = Game(2, 7)
            steps = 0
            while g.phase not in ("play", "redeal"):
                self.assertTrue(g.bid(g.turn, bool(mask & (1 << steps)))[0])
                steps += 1
                self.assertLessEqual(steps, 6)
        g = Game(2, 6)
        caller = g.turn
        for _ in range(4):
            self.assertTrue(g.bid(g.turn, True)[0])
        self.assertEqual((g.lord, g.multiplier, g.turn), (caller, 8, caller))
        g = Game(2, 2)
        for _ in range(3):
            g.bid(g.turn, False)
        self.assertEqual(g.phase, "redeal")
        g.deal()
        self.assertEqual((g.phase, g.deal_number), ("call", 2))

    def test_reject_and_reset(self):
        g = self.play_game()
        p = g.turn
        before = copy.deepcopy(g.__dict__)
        for action in (lambda: g.pass_turn(p), lambda: g.play(p, []),
                       lambda: g.play(p, [g.hands[p][0]] * 2),
                       lambda: g.play((p+1) % 3, [g.hands[(p+1) % 3][0]]),
                       lambda: g.play(p, [55])):
            self.assertFalse(action()[0])
            for key in before:
                if key != "random":
                    self.assertEqual(before[key], g.__dict__[key])
        g.play(p, [g.hands[p][0]])
        g.pass_turn(g.turn)
        g.pass_turn(g.turn)
        self.assertEqual(g.turn, p)
        self.assertEqual(g.round, 2)
        self.assertIsNone(g.last)
        self.assertFalse(g.shown)

    def test_spring_scores_and_bomb(self):
        g = self.play_game()
        g.lord = g.turn = 0
        g.hands = [[1, 2, 3, 4], [5], [6]]
        self.assertTrue(g.play(0, [1, 2, 3, 4])[0])
        self.assertEqual((g.phase, g.spring, g.multiplier), ("over", "春天", 4))
        self.assertEqual(g.scores(), (8, -4, -4))
        self.assertEqual(g.bomb_serial, 1)
        g = self.play_game()
        g.lord, g.turn = 0, 1
        g.hands, g.plays = [[1], [2], [3]], [1, 0, 0]
        g.play(1, [2])
        self.assertEqual(g.spring, "反春天")
        self.assertEqual(g.scores(), (-4, 2, 2))

    def test_fairness_and_public_bottom(self):
        for seed in range(10):
            g = self.play_game(seed, 3)
            p = g.lord
            a, b = (p+1) % 3, (p+2) % 3
            view = g.view(p)
            self.assertFalse(hasattr(view, "hands"))
            g.hands[a], g.hands[b] = g.hands[b], g.hands[a]
            self.assertEqual(view, g.view(p))
            self.assertEqual(ai.choose(view, random.Random(3)), ai.choose(g.view(p), random.Random(3)))
            farmer = g.view(a)
            sampled = ai.sample_hands(farmer, random.Random(5))
            self.assertEqual([sum(h) for h in sampled], list(farmer.remaining))
            for actual, forced in zip(sampled[p], counts(g.bottom)):
                self.assertGreaterEqual(actual, forced)

    def test_complete_games(self):
        # 常规快速回归；更多种子使用 tools/soak.py。
        for difficulty in (1, 2, 3):
            for seed in range(5):
                g = self.play_game(seed, difficulty)
                rng = random.Random(seed+100)
                for _ in range(300):
                    seat = g.turn
                    ids = ai.choose(g.view(seat), rng)
                    result = g.play(seat, ids) if ids else g.pass_turn(seat)
                    self.assertTrue(result[0], result[1])
                    held = sum(g.hands, [])
                    played = [c for a in g.history for c in a.cards]
                    self.assertEqual(sorted(held+played), list(range(1, 55)))
                    if g.phase == "over":
                        self.assertFalse(g.hands[g.winner])
                        self.assertEqual(sum(g.scores()), 0)
                        break
                else:
                    self.fail("对局未能在 300 步内结束")


if __name__ == "__main__":
    unittest.main()
