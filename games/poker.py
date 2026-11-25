"""Техасский холдем, 2-6 игроков, стек 1000, блайнды 10/20 (x2 каждые 6 раздач), сайд-поты.
Игра идёт до одного оставшегося игрока. Между раздачами любой игрок жмёт «Дальше»."""
import random
from collections import Counter
from itertools import combinations
from .common import BaseGame, GameError, new_deck

RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
RV = {r: i + 2 for i, r in enumerate(RANKS)}
STACK, SB0, BLIND_EVERY = 1000, 10, 6
HAND_NAMES = ["Старшая карта", "Пара", "Две пары", "Сет", "Стрит", "Флеш", "Фулл-хаус", "Каре", "Стрит-флеш"]


def rank5(cards):
    rs = sorted((c[0] for c in cards), reverse=True)
    flush = len({c[1] for c in cards}) == 1
    uniq = sorted(set(rs), reverse=True)
    sh = None
    if len(uniq) == 5:
        if uniq[0] - uniq[4] == 4: sh = uniq[0]
        elif uniq == [14, 5, 4, 3, 2]: sh = 5
    groups = sorted(Counter(rs).items(), key=lambda x: (x[1], x[0]), reverse=True)
    pat, rk = [g[1] for g in groups], [g[0] for g in groups]
    if sh and flush: return (8, sh)
    if pat == [4, 1]: return (7, *rk)
    if pat == [3, 2]: return (6, *rk)
    if flush: return (5, *rs)
    if sh: return (4, sh)
    if pat == [3, 1, 1]: return (3, *rk)
    if pat == [2, 2, 1]: return (2, *rk)
    if pat == [2, 1, 1, 1]: return (1, *rk)
    return (0, *rs)


def best_hand(cards):
    parsed = [(RV[c[:-1]], c[-1]) for c in cards]
    return max(rank5(c) for c in combinations(parsed, 5))


class Poker(BaseGame):
    def __init__(self, players):
        super().__init__(players)
        self.stack = {p: STACK for p in players}
        self.hand_no = 0
        self.dealer = random.randrange(len(players))
        self.phase = "idle"
        self.last = None
        self._start_hand()

    @property
    def blinds(self):
        sb = SB0 * (2 ** ((max(self.hand_no, 1) - 1) // BLIND_EVERY))
        return sb, sb * 2

    # ---- hand lifecycle
    def _alive(self):
        return [p for p in self.players if self.stack[p] > 0]

    def _start_hand(self):
        alive = self._alive()
        if len(alive) <= 1:
            self.finished = True
            self.winners = alive
            self.result_text = "Победитель: " + "".join("{name:%d}" % p for p in alive)
            self.phase = "over"
            return
        self.hand_no += 1
        self.phase = "play"
        self.deck = new_deck(RANKS)
        self.board, self.street = [], "preflop"
        # dealer button -> next alive seat
        n = len(self.players)
        i = (self.dealer + 1) % n
        while self.stack[self.players[i]] <= 0:
            i = (i + 1) % n
        self.dealer = i
        self.order = [self.players[(i + k) % n] for k in range(n) if self.stack[self.players[(i + k) % n]] > 0]
        self.button = self.order[0]
        self.hole = {p: [self.deck.pop(), self.deck.pop()] for p in self.order}
        self.folded, self.total, self.bet = set(), {p: 0 for p in self.order}, {p: 0 for p in self.order}
        self.acted, self.revealed, self.last = set(), set(), None
        sb_amt, bb_amt = self.blinds
        if len(self.order) == 2:
            sb, bb = self.order[0], self.order[1]
        else:
            sb, bb = self.order[1], self.order[2]
        self._pay(sb, sb_amt)
        self._pay(bb, bb_amt)
        self.cur_bet, self.min_raise = max(self.bet.values()), bb_amt
        self._progress(bb)

    def _pay(self, p, n):
        n = min(n, self.stack[p])
        self.stack[p] -= n
        self.bet[p] += n
        self.total[p] += n

    def _live(self):
        return [p for p in self.order if p not in self.folded]

    def _need(self):
        can = [p for p in self._live() if self.stack[p] > 0]
        if len(can) == 1 and self.bet[can[0]] >= self.cur_bet:
            return []
        return [p for p in can if self.bet[p] < self.cur_bet or p not in self.acted]

    def _progress(self, after):
        live = self._live()
        if len(live) == 1:
            return self._award_uncontested(live[0])
        need = self._need()
        if not need:
            return self._next_street()
        i = self.order.index(after)
        for k in range(1, len(self.order) + 1):
            p = self.order[(i + k) % len(self.order)]
            if p in need:
                self.turn = p
                return

    def _next_street(self):
        if self.street == "river":
            return self._showdown()
        self.street = {"preflop": "flop", "flop": "turn", "turn": "river"}[self.street]
        self.board += [self.deck.pop() for _ in range(3 if self.street == "flop" else 1)]
        self.bet = {p: 0 for p in self.order}
        self.cur_bet, self.min_raise, self.acted = 0, self.blinds[1], set()
        self._progress(self.button)

    def _award_uncontested(self, p):
        pot = sum(self.total.values())
        self.stack[p] += pot
        self.last = {"winners": [{"id": p, "amount": pot, "hand": None}], "shown": {}, "board": self.board}
        self.turn, self.phase = None, "result"
        self._check_over()

    def _showdown(self):
        live = self._live()
        while len(self.board) < 5:
            self.board.append(self.deck.pop())
        scores = {p: best_hand(self.hole[p] + self.board) for p in live}
        contrib, won, wins = dict(self.total), Counter(), {}
        while any(v > 0 for v in contrib.values()):
            elig = [p for p in live if contrib[p] > 0]
            if not elig:
                elig = [max(live, key=lambda q: self.total[q])]
                pot = sum(contrib.values())
                contrib = {p: 0 for p in contrib}
            else:
                lvl = min(contrib[p] for p in elig)
                pot = sum(min(v, lvl) for v in contrib.values() if v > 0)
                contrib = {p: max(0, v - lvl) if v > 0 else 0 for p, v in contrib.items()}
            top = max(scores[p] for p in elig)
            ws = [p for p in elig if scores[p] == top]
            share, rem = divmod(pot, len(ws))
            for k, p in enumerate(ws):
                won[p] += share + (rem if k == 0 else 0)
        for p, amt in won.items():
            self.stack[p] += amt
        self.last = {"winners": [{"id": p, "amount": a, "hand": HAND_NAMES[scores[p][0]]} for p, a in won.items()],
                     "shown": {p: self.hole[p] for p in live}, "board": self.board}
        self.turn, self.phase = None, "result"
        self._check_over()

    def _check_over(self):
        if len(self._alive()) <= 1:
            self.finished = True
            self.winners = self._alive()
            self.result_text = "Победитель: " + "".join("{name:%d}" % p for p in self.winners)

    # ---- actions
    def act(self, uid, a):
        if self.finished and self.phase != "result":
            raise GameError("Игра закончилась")
        k = a.get("a")
        if k == "next":
            if uid not in self.players:
                raise GameError("Ты зритель")
            if self.phase != "result" or self.finished:
                raise GameError("Раздача ещё идёт")
            return self._start_hand()
        if self.phase != "play" or uid != self.turn:
            raise GameError("Сейчас не твой ход")
        to_call = self.cur_bet - self.bet[uid]
        if k == "fold":
            self.folded.add(uid)
        elif k == "check":
            if to_call > 0:
                raise GameError("Нужно уравнять или сбросить")
            self.acted.add(uid)
        elif k == "call":
            self._pay(uid, to_call)
            self.acted.add(uid)
        elif k == "raise":
            try:
                to = int(a.get("amount"))
            except (TypeError, ValueError):
                raise GameError("Неверная сумма")
            all_in = to >= self.bet[uid] + self.stack[uid]
            to = min(to, self.bet[uid] + self.stack[uid])
            if to <= self.cur_bet and not all_in:
                raise GameError("Рейз должен быть больше текущей ставки")
            if to < self.cur_bet + self.min_raise and not all_in:
                raise GameError(f"Минимальный рейз до {self.cur_bet + self.min_raise}")
            old = self.cur_bet
            self._pay(uid, to - self.bet[uid])
            if self.bet[uid] > old:
                self.cur_bet = self.bet[uid]
                self.min_raise = max(self.min_raise, self.cur_bet - old)
                self.acted = {uid}
            else:
                self.acted.add(uid)
        else:
            raise GameError("Неизвестное действие")
        self._progress(uid)

    # ---- view
    def view(self, viewer):
        pl = []
        for p in self.players:
            seated = p in self.hole
            cards = None
            if seated and p not in self.folded:
                if p == viewer or (self.phase in ("result", "over") and self.last and p in self.last["shown"]):
                    cards = self.hole[p]
            pl.append({"id": p, "stack": self.stack[p], "bet": self.bet.get(p, 0) if seated else 0,
                       "folded": p in self.folded if seated else True, "in_hand": seated,
                       "allin": seated and self.stack[p] == 0 and p not in self.folded,
                       "cards": cards})
        you = None
        if viewer == getattr(self, "turn", None) and self.phase == "play":
            tc = min(self.cur_bet - self.bet[viewer], self.stack[viewer])
            you = {"to_call": tc, "min_to": min(self.cur_bet + self.min_raise, self.bet[viewer] + self.stack[viewer]),
                   "max_to": self.bet[viewer] + self.stack[viewer]}
        return {"game": "poker", "phase": self.phase, "street": self.street, "board": self.board,
                "pot": sum(self.total.values()), "players": pl, "button": self.button,
                "turn": self.turn if self.phase == "play" else None, "you": you,
                "hand_no": self.hand_no, "blinds": self.blinds, "last": self.last, "finished": self.finished}
