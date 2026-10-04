"""长对局测试：python tools/soak.py --games 100（每档难度的局数）。"""
import argparse
from pathlib import Path
import random
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import Game
import ai


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=100)
    args = parser.parse_args()
    started = time.monotonic()
    total_actions = 0
    slowest = 0
    for difficulty in (1, 2, 3):
        for seed in range(args.games):
            g = Game(difficulty, seed)
            rng = random.Random(seed+10000)
            for step in range(700):
                if g.phase == "redeal":
                    g.deal()
                    continue
                seat = g.turn
                if g.phase != "play":
                    result = g.bid(seat, ai.bid(g.view(seat), rng))
                else:
                    before = time.monotonic()
                    cards = ai.choose(g.view(seat), rng)
                    slowest = max(slowest, time.monotonic()-before)
                    result = g.play(seat, cards) if cards else g.pass_turn(seat)
                    total_actions += 1
                    held = sum(g.hands, [])
                    played = [c for a in g.history for c in a.cards]
                    assert sorted(held+played) == list(range(1, 55)), (difficulty, seed, step)
                assert result[0], (difficulty, seed, step, result)
                if g.phase == "over":
                    assert not g.hands[g.winner]
                    assert sum(g.scores()) == 0
                    break
            else:
                raise AssertionError((difficulty, seed, "未终局"))
        print(f"difficulty={difficulty}: {args.games} games passed", flush=True)
    print(f"total={args.games*3}, actions={total_actions}, slowest_ai={slowest:.3f}s, elapsed={time.monotonic()-started:.1f}s")


if __name__ == "__main__":
    main()
