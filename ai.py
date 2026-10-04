"""公平 AI：公开记牌、手牌整理、队友配合及有界残局抽样搜索。"""
import random
import time
from core import counts, subtract, same_team, legal_moves, cards_for


def unseen(view):
    known = set(view.hand)
    for action in view.history:
        known.update(action.cards)
    pool = [c for c in range(1, 55) if c not in known]
    return counts(pool), pool, known


def shape(c):
    cost = sum((1.35, 1.05, .9, .4)[n - 1] + max(0, 9 - i) * .025
               for i, n in enumerate(c) if n)
    for unit, minimum, weight in ((1, 5, .55), (2, 3, .60), (3, 2, .65)):
        run = 0
        for i in range(13):
            if i < 12 and c[i] >= unit:
                run += 1
            else:
                if run >= minimum:
                    cost -= run * weight
                run = 0
    return cost - (1.7 if c[13] and c[14] else 0)


def split_cost(c, move):
    cost = sum(6 if c[i] == 4 else 1.4 if c[i] == 3 else .65
               for i in range(15) if 0 < move.c[i] < c[i])
    if c[13] and c[14] and move.kind != "rocket" and (move.c[13] or move.c[14]):
        cost += 7
    return cost


def pressure(view):
    return min(view.remaining[p] for p in range(3)
               if not same_team(p, view.seat, view.lord))


class Budget:
    def __init__(self, nodes=300, deadline=float("inf")):
        self.nodes, self.deadline = nodes, deadline

    def take(self):
        if self.nodes <= 0 or time.monotonic() >= self.deadline:
            return False
        self.nodes -= 1
        return True


def hand_steps(c, memo, budget):
    if not any(c):
        return 0
    if c in memo:
        return memo[c]
    if not budget.take():
        return max(1, shape(c))
    moves = legal_moves(c)
    if moves[0].n == sum(c):
        memo[c] = 1
        return 1
    value = min(1 + hand_steps(subtract(c, m.c), memo, budget) for m in moves[:24])
    memo[c] = value
    return value


def score_move(view, c, move, unseen_counts, memo, budget):
    left = subtract(c, move.c)
    rest = sum(left)
    if rest == 0:
        return -100000
    danger = pressure(view)
    hard = view.difficulty == 3
    value = shape(left) * 4 - move.n * .65 + move.rank * .09 + split_cost(c, move) * (2 if hard else 1.3)
    if move.kind in ("bomb", "rocket"):
        value += 4 if danger <= 2 else 15
    if hard and rest <= 9:
        value += hand_steps(left, memo, budget) * 2.5
    if move.kind in ("single", "pair"):
        higher = sum(n >= move.n for n in unseen_counts[move.rank - 2:])
        weight = (2.5 if danger <= 2 else .15) if hard else (1.3 if danger <= 2 else .08)
        value += higher * weight
    if danger <= 2:
        if move.n == danger:
            value += (18 - move.rank) * 2.5
        if view.last is None and move.n > danger:
            value -= 8
    ally = (view.seat + 1) % 3
    if view.seat != view.lord and view.last is None and ally != view.lord:
        if view.remaining[ally] <= 2 and move.n == view.remaining[ally]:
            value -= max(0, 15 - move.rank) * .9
    return value


def ranked_moves(view):
    """给提示提供稳定的合法候选；不使用随机数、不改变发牌或 AI 随机状态。"""
    c = counts(view.hand)
    u, _, _ = unseen(view)
    memo, budget = {}, Budget(50, time.monotonic() + .2)
    return sorted(legal_moves(c, view.last),
                  key=lambda m: (score_move(view, c, m, u, memo, budget), m.rank, m.c))


def sample_hands(view, rng, pool=None, known=None):
    if pool is None:
        _, pool, known = unseen(view)
    hands = [[], [], []]
    hands[view.seat] = list(view.hand)
    forced = set(view.bottom) - known
    if forced:
        hands[view.lord].extend(forced)
    free = [c for c in pool if c not in forced]
    rng.shuffle(free)
    pos = 0
    for p in range(3):
        if p == view.seat:
            continue
        need = view.remaining[p] - len(hands[p])
        if need < 0 or pos + need > len(free):
            return None
        hands[p].extend(free[pos:pos + need])
        pos += need
    return [counts(h) for h in hands] if pos == len(free) else None


def solve(hands, turn, last, passes, lord, team, budget, depth, cache):
    """确定牌分布下的三人队伍极小极大；1 赢、-1 输、0 未算完。"""
    for p, hand in enumerate(hands):
        if not any(hand):
            return 1 if same_team(p, team, lord) else -1
    if depth <= 0 or not budget.take():
        return 0
    signature = None if last is None else (last.kind, last.rank, last.n, last.length)
    key = (tuple(hands), turn, signature, passes)
    if key in cache:
        return cache[key]
    maximize = same_team(turn, team, lord)
    best = -1 if maximize else 1
    moves = legal_moves(hands[turn], last)
    if last is not None:
        moves.append(None)
    for move in moves:
        if move is not None:
            child = hands[:]
            child[turn] = subtract(child[turn], move.c)
            value = solve(child, (turn + 1) % 3, move, 0, lord, team, budget, depth - 1, cache)
        else:
            value = solve(hands, (turn + 1) % 3, None if passes == 1 else last,
                          (passes + 1) % 2, lord, team, budget, depth - 1, cache)
        best = max(best, value) if maximize else min(best, value)
        if best == (1 if maximize else -1):
            cache[key] = best
            return best
    if best != 0:
        cache[key] = best
    return best


def choose(view, rng=None):
    rng = rng or random.Random()
    c = counts(view.hand)
    moves = legal_moves(c, view.last)
    if not moves:
        return None
    for move in moves:
        if move.n == len(view.hand):
            return cards_for(view.hand, move.c)
    if view.difficulty == 1:
        if view.last and rng.random() < .22:
            return None
        move = rng.choice(moves) if rng.random() < .45 else min(moves, key=lambda m: (m.rank, m.n))
        return cards_for(view.hand, move.c)
    danger = pressure(view)
    if view.last_seat is not None and same_team(view.seat, view.last_seat, view.lord):
        if view.remaining[view.last_seat] <= 2 or view.last.rank >= 13 or danger > 2:
            return None
    u, pool, known = unseen(view)
    deadline = time.monotonic() + .8
    memo, budget = {}, Budget(70, deadline)
    moves.sort(key=lambda m: (score_move(view, c, m, u, memo, budget), m.rank, m.c))
    best = moves[0]
    if view.last and best.kind in ("bomb", "rocket") and danger > 4 and len(view.hand) > best.n + 3:
        return None
    if view.difficulty == 3 and sum(view.remaining) <= 12:
        candidates = moves[:6] + ([None] if view.last else [])
        totals = [0] * len(candidates)
        for _ in range(6):
            hands = sample_hands(view, rng, pool, known)
            if hands is None or time.monotonic() >= deadline:
                break
            values = []
            for move in candidates:
                state = hands[:]
                target, passes = move, 0
                if move is None:
                    target = None if view.passes == 1 else view.last
                    passes = (view.passes + 1) % 2
                else:
                    state[view.seat] = subtract(state[view.seat], move.c)
                values.append(solve(state, (view.seat + 1) % 3, target, passes,
                                    view.lord, view.seat, Budget(240, deadline), 30, {}))
            # 只累计完整的一轮，避免时间截止偏向较早候选。
            if time.monotonic() < deadline:
                totals = [a + b for a, b in zip(totals, values)]
        best = candidates[max(range(len(candidates)), key=lambda i: totals[i])]
    return cards_for(view.hand, best.c) if best is not None else None


def bid(view, rng=None):
    rng = rng or random.Random()
    c = counts(view.hand)
    if view.difficulty == 1:
        return rng.random() < .48
    strength = sum(n == 4 for n in c[:13]) * 3 + c[12] * .8 + c[13] * 1.5 + c[14] * 2.2
    if c[13] and c[14]:
        strength += 2
    return strength + (rng.random() - .5) * 1.2 >= (3.6 if view.phase == "call" else 4.8)
