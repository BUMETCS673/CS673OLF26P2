"""When an account can add to what other learners search, and when reports take that away.

Trust is stored on the user and changed only by the two events that can change it, so reading it
costs one column.
"""

from datetime import datetime, timedelta

from app.models import User
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.users import UserRepository

# Starting points, to tune. Together they make many accounts cost days of real study each.
TRUST_ACCOUNT_AGE = timedelta(days=7)
TRUST_FINISHED_DECKS = 3
# Trust is lost once this many different trusted learners report an account's content in the
# window. After a loss it can't come back sooner than the window, and only through new study.
TRUST_LOSS_REPORTERS = 3
TRUST_LOSS_WINDOW = timedelta(days=90)


def _may_earn(user: User, now: datetime) -> bool:
    if user.trusted_at is not None or now - user.created_at < TRUST_ACCOUNT_AGE:
        return False
    return user.trust_lost_at is None or now - user.trust_lost_at >= TRUST_LOSS_WINDOW


async def grant_if_earned(
    user: User,
    deck_id: int,
    now: datetime,
    users: UserRepository,
    knowledge: KnowledgeRepository,
) -> None:
    """After a card in `deck_id` reaches review, the only answer that can finish a deck.

    Cheapest checks first: most calls end on the loaded user, and the full count runs only when
    this deck is finished.
    """
    if not _may_earn(user, now):
        return
    since = user.trust_lost_at
    if not await users.deck_is_finished(deck_id, since):
        return
    if await users.count_finished_decks(user.id, since) < TRUST_FINISHED_DECKS:
        return
    await users.grant_trust(user.id, now)
    await knowledge.share_waiting_chunks(user.id)


async def revoke_if_reported(
    user_id: int, now: datetime, users: UserRepository, knowledge: KnowledgeRepository
) -> None:
    """After a trusted report against `user_id`. Only reports since trust was earned count."""
    trusted_at = await users.trusted_at(user_id)
    if trusted_at is None:
        return
    since = max(trusted_at, now - TRUST_LOSS_WINDOW)
    if await users.trusted_reporters_against(user_id, since) >= TRUST_LOSS_REPORTERS:
        await users.revoke_trust(user_id, now)
        await knowledge.hide_user(user_id)
