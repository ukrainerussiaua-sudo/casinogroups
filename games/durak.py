"""Подкидной дурак, 36 карт, 2-6 игроков.
Card = rank+suit, e.g. "10H". Deck pops from the end; deck[0] is the trump card (drawn last)."""
import random
from .common import BaseGame, GameError, new_deck

RANKS = ["6", "7", "8", "9", "10", "J", "Q", "K", "A"]


def rank(c): return c[:-1]
def suit(c): return c[-1]
def rv(c): return RANKS.index(rank(c))


class Durak(BaseGame):
    def __init__(self, players):
        super().__init__(players)
        self.deck = new_deck(RANKS)
        self.trump_card = self.deck[0]
        self.trump = suit(self.trump_card)
        self.hands = {p: [self.deck.pop() for _ in range(6)] for p in self.players}
        self.discard = 0
        self.active = list(self.players)
        # first attacker: lowest trump in hand, else random
        best, first = None, None
        for p in self.players:
            for c in self.hands[p]:
                if suit(c) == self.trump and (best is None or rv(c) < best):
                    best, first = rv(c), p
        self.attacker = first or random.choice(self.players)
        self._new_bout()
        self.loser = None

    # ---- helpers
    def _next(self, p, seq=None):
        seq = seq or self.active
        return seq[(seq.index(p) + 1) % len(seq)]

    def _new_bout(self):
        self.defender = self._next(self.attacker)
        self.table = []          # [[attack, defense|None], ...]
        self.phase = "attack"    # attack | taking
        self.limit = min(6, len(self.hands[self.defender]))

    def _beats(self, d, a):
        if suit(d) == suit(a):
            return rv(d) > rv(a)
        return suit(d) == self.trump

    def _ranks_on_table(self):
        return {rank(c) for pair in self.table for c in pair if c}

    # ---- actions
    def act(self, uid, a):
        if self.finished:
            raise GameError("Игра уже закончилась")
        if uid not in self.active:
            raise GameError("Ты не в игре")
        kind = a.get("a")
        if kind == "play":
            card = a.get("card")
            if card not in self.hands[uid]:
                raise GameError("Нет такой карты")
            if uid == self.defender:
                self._defend(uid, card)
            else:
                self._attack(uid, card)
        elif kind == "take":
            if uid != self.defender or self.phase != "attack" or not self.table:
                raise GameError("Сейчас нельзя взять")
            self.phase = "taking"
        elif kind == "done":
            if uid != self.attacker:
                raise GameError("Завершает ход атакующий")
            if self.phase == "taking":
                self._end_bout(took=True)
            else:
                if not self.table:
                    raise GameError("Стол пуст")
                if any(d is None for _, d in self.table):
                    raise GameError("Не все карты отбиты")
                self._end_bout(took=False)
        else:
            raise GameError("Неизвестное действие")

    def _attack(self, uid, card):
        if not self.table and uid != self.attacker:
            raise GameError("Первый ход делает атакующий")
        if self.table and rank(card) not in self._ranks_on_table():
            raise GameError("Подкинуть можно только по достоинству карт на столе")
        if len(self.table) >= self.limit:
            raise GameError("Лимит карт на стол")
        if self.phase == "attack":
            open_cnt = sum(1 for _, d in self.table if d is None)
            if open_cnt >= len(self.hands[self.defender]):
                raise GameError("У защитника не хватит карт")
        self.hands[uid].remove(card)
        self.table.append([card, None])

    def _defend(self, uid, card):
        if self.phase != "attack":
            raise GameError("Ты уже берёшь")
        tgt = a_idx = None
        for i, (att, d) in enumerate(self.table):
            if d is None and self._beats(card, att):
                a_idx = i
                break
        if a_idx is None:
            raise GameError("Этой картой нечего бить")
        self.hands[uid].remove(card)
        self.table[a_idx][1] = card

    def _end_bout(self, took):
        old_active = list(self.active)
        d = self.defender
        cards = [c for pair in self.table for c in pair if c]
        if took:
            self.hands[d].extend(cards)
        else:
            self.discard += len(cards)
        # draw: attacker first, other throwers, defender last
        seq, p = [], self.attacker
        for _ in old_active:
            if p != d:
                seq.append(p)
            p = self._next(p, old_active)
        seq.append(d)
        for p in seq:
            while len(self.hands[p]) < 6 and self.deck:
                self.hands[p].append(self.deck.pop())
        new_active = [p for p in old_active if self.hands[p] or self.deck]
        cand = self._next(d, old_active) if took else d
        for _ in range(len(old_active)):
            if cand in new_active:
                break
            cand = self._next(cand, old_active)
        if len(new_active) <= 1:
            self.active = new_active
            self.finished = True
            self.loser = new_active[0] if new_active else None
            self.winners = [p for p in self.players if p != self.loser]
            self.result_text = "Ничья" if self.loser is None else "Дурак: {name:%d}" % self.loser
            return
        self.active, self.attacker = new_active, cand
        self._new_bout()

    # ---- view
    def view(self, viewer):
        return {
            "game": "durak", "trump": self.trump_card, "deck": len(self.deck),
            "discard": self.discard, "table": self.table, "phase": self.phase,
            "attacker": self.attacker, "defender": self.defender,
            "active": self.active, "order": self.players,
            "counts": {p: len(h) for p, h in self.hands.items()},
            "hand": self.hands.get(viewer) if viewer in self.players else None,
            "finished": self.finished, "loser": self.loser,
        }
