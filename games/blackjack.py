"""Блэкджек против дилера. 2-6 игроков за столом, 5 раундов, фиксированная ставка 100, стек 1000.
Зрители видят только открытую карту дилера и количество карт у игроков."""
from .common import BaseGame, GameError, new_deck

RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
ROUNDS, BET, STACK = 5, 100, 1000


def value(hand):
    t = sum(10 if c[:-1] in "JQK" else 11 if c[:-1] == "A" else int(c[:-1]) for c in hand)
    aces = sum(1 for c in hand if c[:-1] == "A")
    while t > 21 and aces:
        t -= 10
        aces -= 1
    return t


class Blackjack(BaseGame):
    def __init__(self, players):
        super().__init__(players)
        self.chips = {p: STACK for p in players}
        self.round = 0
        self.phase = "idle"
        self.deck = []
        self._deal()

    def _draw(self):
        if len(self.deck) < 15:
            self.deck = new_deck(RANKS) + new_deck(RANKS)
        return self.deck.pop()

    def _deal(self):
        self.round += 1
        self.phase = "play"
        self.seated = [p for p in self.players if self.chips[p] > 0]
        self.bets = {p: min(BET, self.chips[p]) for p in self.seated}
        self.hands = {p: [self._draw(), self._draw()] for p in self.seated}
        self.dealer = [self._draw(), self._draw()]
        self.done = {p: value(self.hands[p]) == 21 for p in self.seated}
        self.deltas = {}
        self.turn = None
        self._advance()

    def _advance(self):
        for p in self.seated:
            if not self.done[p]:
                self.turn = p
                return
        self.turn = None
        while value(self.dealer) < 17:
            self.dealer.append(self._draw())
        dv = value(self.dealer)
        dealer_bj = len(self.dealer) == 2 and dv == 21
        for p in self.seated:
            h, b = self.hands[p], self.bets[p]
            v = value(h)
            bj = len(h) == 2 and v == 21
            if v > 21: d = -b
            elif bj and not dealer_bj: d = b * 3 // 2
            elif dealer_bj and not bj: d = -b
            elif dv > 21 or v > dv: d = b
            elif v == dv: d = 0
            else: d = -b
            self.deltas[p] = d
            self.chips[p] += d
        self.phase = "result"
        if self.round >= ROUNDS or sum(1 for p in self.players if self.chips[p] > 0) == 0:
            self._finish()

    def _finish(self):
        top = max(self.chips.values())
        self.winners = [p for p in self.players if self.chips[p] == top]
        self.finished = True
        self.result_text = "Победитель: " + ", ".join("{name:%d}" % p for p in self.winners) + f" ({top} фишек)"

    def act(self, uid, a):
        if self.finished:
            raise GameError("Игра закончилась")
        k = a.get("a")
        if k == "next":
            if uid not in self.players:
                raise GameError("Ты зритель")
            if self.phase != "result":
                raise GameError("Раунд ещё идёт")
            self._deal()
            return
        if self.phase != "play" or uid != self.turn:
            raise GameError("Сейчас не твой ход")
        h = self.hands[uid]
        if k == "hit":
            h.append(self._draw())
            if value(h) >= 21:
                self.done[uid] = True
        elif k == "stand":
            self.done[uid] = True
        elif k == "double":
            if len(h) != 2 or self.chips[uid] < self.bets[uid] * 2:
                raise GameError("Удвоить нельзя")
            self.bets[uid] *= 2
            h.append(self._draw())
            self.done[uid] = True
        else:
            raise GameError("Неизвестное действие")
        self._advance()

    def view(self, viewer):
        is_p = viewer in self.players
        reveal = self.phase == "result" or self.finished
        hands = {}
        for p in self.seated:
            show = is_p or reveal
            hands[p] = {"cards": self.hands[p] if show else None, "n": len(self.hands[p]),
                        "total": value(self.hands[p]) if show else None,
                        "bet": self.bets[p], "done": self.done[p], "delta": self.deltas.get(p)}
        dealer = self.dealer if reveal else [self.dealer[0]]
        return {"game": "blackjack", "round": self.round, "rounds": ROUNDS, "phase": self.phase,
                "turn": self.turn, "chips": self.chips, "hands": hands, "seated": self.seated,
                "dealer": dealer, "dealer_hidden": 0 if reveal else 1,
                "dealer_total": value(self.dealer) if reveal else None, "finished": self.finished}
