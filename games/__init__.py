from .durak import Durak
from .blackjack import Blackjack
from .poker import Poker
from .tetris import Tetris
from .common import GameError

REGISTRY = {
    "durak":     dict(cls=Durak,     title="Дурак",     emoji="🃏", min=2, max=6),
    "blackjack": dict(cls=Blackjack, title="Блэкджек",  emoji="♠️", min=2, max=6),
    "poker":     dict(cls=Poker,     title="Покер",     emoji="♦️", min=2, max=6),
    "tetris":    dict(cls=Tetris,    title="Тетрис",    emoji="🧱", min=2, max=4),
}
