import random

SUITS = "SHDC"


class GameError(Exception):
    """Illegal move / wrong turn. Message is shown to the player as a toast."""


class BaseGame:
    finished = False
    winners: list = []
    result_text = ""
    events: list  # outgoing per-user messages: [{"to": uid, "t": "garbage", "n": 2}]

    def __init__(self, players):
        self.players = list(players)
        self.events = []

    def act(self, uid, a):
        raise NotImplementedError

    def view(self, viewer):
        raise NotImplementedError

    def is_player(self, uid):
        return uid in self.players


def new_deck(ranks):
    d = [r + s for s in SUITS for r in ranks]
    random.shuffle(d)
    return d
