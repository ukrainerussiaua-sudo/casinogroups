"""Тетрис-батл 2-4 игрока. Физика считается на клиентах (общий seed), сервер:
синхронизирует старт, пересылает доски зрителям/соперникам, раздаёт мусорные линии, определяет победителя."""
import random
import time
from .common import BaseGame, GameError

GARBAGE = {1: 0, 2: 1, 3: 2, 4: 4}
EMPTY_ROW = "." * 10


class Tetris(BaseGame):
    def __init__(self, players):
        super().__init__(players)
        self.seed = random.randrange(1, 2 ** 31)
        self.start_at = int(time.time() * 1000) + 6000
        self.boards = {p: [EMPTY_ROW] * 20 for p in players}
        self.score = {p: 0 for p in players}
        self.alive = list(players)
        self.dead_order = []

    def act(self, uid, a):
        if uid not in self.players:
            raise GameError("Ты зритель")
        if self.finished or uid not in self.alive:
            return
        k = a.get("a")
        if k == "board":
            b = a.get("rows")
            if isinstance(b, list) and len(b) == 20 and all(isinstance(r, str) and len(r) == 10 for r in b):
                self.boards[uid] = b
            self.score[uid] = int(a.get("score") or 0)
        elif k == "lines":
            n = GARBAGE.get(int(a.get("n") or 0), 0)
            if n:
                for p in self.alive:
                    if p != uid:
                        self.events.append({"to": p, "t": "garbage", "n": n})
        elif k == "dead":
            self.alive.remove(uid)
            self.dead_order.append(uid)
            if len(self.alive) <= 1:
                self.finished = True
                self.winners = list(self.alive)
                self.result_text = "Победитель: " + "".join("{name:%d}" % p for p in self.winners)
        else:
            raise GameError("Неизвестное действие")

    def view(self, viewer):
        return {"game": "tetris", "seed": self.seed, "start_at": self.start_at, "now": int(time.time() * 1000),
                "boards": self.boards, "score": self.score, "alive": self.alive,
                "order": self.players, "finished": self.finished}
