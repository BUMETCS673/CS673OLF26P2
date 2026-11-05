"""When an account can add to what other learners search, and when reports take that away.

Trust is stored on the user and changed only by the two events that can change it, so reading it
costs one column.
"""

import logging
from datetime import datetime, timedelta

from app.models import User
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.users import UserRepository

logger = logging.getLogger(__name__)

# Starting points, to tune. Together they make many accounts cost days of real study each.
TRUST_ACCOUNT_AGE = timedelta(days=7)
TRUST_FINISHED_DECKS = 3
# Trust is lost once this many different trusted learners report an account's content in the
# window. After a loss it can't come back sooner than the window, and only through new study.
TRUST_LOSS_REPORTERS = 3
TRUST_LOSS_WINDOW = timedelta(days=90)


def _may_earn(user: User, now: datetime) -> bool:
    # already trusted or the account is under 7 days old
    if user.trusted_at is not None or now - user.created_at < TRUST_ACCOUNT_AGE:
        return False
    # never lost trust or lost it over 90 days ago
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
    # Step 1: skip users already trusted, too new or still in the wait after losing trust
    if not _may_earn(user, now):  # no query decided from the user already loaded
        return

    # Step 2: skip unless this deck is now finished counting only study since trust was lost
    since = user.trust_lost_at  # None counts all study
    if not await users.deck_is_finished(deck_id, since):  # a cheap query on one deck
        return

    # Step 3: skip unless the user has finished enough decks
    # the costlier count across all decks only reached when this deck just finished
    if await users.count_finished_decks(user.id, since) < TRUST_FINISHED_DECKS:
        return

    # Step 4: grant trust and share the chunks that were waiting for it
    await users.grant_trust(user.id, now)
    await knowledge.share_waiting_chunks(user.id)  # their held-back chunks join shared search
    logger.info("trust granted", extra={"user_id": user.id, "deck_id": deck_id})


async def revoke_if_reported(
    user_id: int, now: datetime, users: UserRepository, knowledge: KnowledgeRepository
) -> None:
    """After a trusted report against `user_id`. Only reports since trust was earned count."""
    # Step 1: skip a user who isn't trusted
    trusted_at = await users.trusted_at(user_id)  # one column not the whole user
    if trusted_at is None:  # nothing to take away
        return

    # Step 2: count the different trusted learners who reported them in the window
    # from when trust was earned or 90 days ago whichever is later
    since = max(trusted_at, now - TRUST_LOSS_WINDOW)
    # distinct reporters so one learner reporting many cards counts once
    reporters = await users.trusted_reporters_against(user_id, since)

    # Step 3: at the threshold take trust away and hide everything they shared
    if reporters >= TRUST_LOSS_REPORTERS:  # 3 different trusted reporters
        await users.revoke_trust(user_id, now)  # starts the 90-day wait before earning again
        await knowledge.hide_user(user_id)  # all their shared chunks leave search at once
        logger.info("trust revoked", extra={"user_id": user_id, "reporters": reporters})
