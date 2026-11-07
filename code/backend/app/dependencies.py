"""What routes can ask FastAPI for: services, and the signed-in user."""

from typing import Annotated

from fastapi import Cookie, Depends

from app.ai.knowledge.cache import RedisByteStore
from app.core.database import SessionDep
from app.core.errors import found
from app.core.redis import get_redis
from app.core.settings import get_settings
from app.jobs.events import JobEvents
from app.models import Deck, User
from app.repositories.unit_of_work import UnitOfWork
from app.schemas.jobs import JobRead
from app.services.api_tokens import ApiTokenService
from app.services.auth import AuthService
from app.services.budget import BudgetService
from app.services.cards import CardService
from app.services.decks import DECK_NOT_FOUND, DeckService
from app.services.generations import GenerationService
from app.services.jobs import JobService
from app.services.materials import MaterialService
from app.services.oauth import OAuthService
from app.services.oauth_tokens import OAuthTokenService
from app.services.problem_cards import ProblemCardService
from app.services.study import StudyService
from app.services.tutor import TutorService

SESSION_COOKIE = "session"


def get_unit_of_work(session: SessionDep) -> UnitOfWork:
    # FastAPI builds one per request and every service in that request shares it
    return UnitOfWork(session)


UnitOfWorkDep = Annotated[UnitOfWork, Depends(get_unit_of_work)]


def get_auth_service(tx: UnitOfWorkDep) -> AuthService:
    return AuthService(tx.session, tx.users, get_settings())


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
SessionToken = Annotated[str | None, Cookie(alias=SESSION_COOKIE)]


async def get_current_user(service: AuthServiceDep, token: SessionToken = None) -> User:
    return await service.user_for_token(token)


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_api_token_service(tx: UnitOfWorkDep) -> ApiTokenService:
    return ApiTokenService(tx.session, tx.api_tokens)


ApiTokenServiceDep = Annotated[ApiTokenService, Depends(get_api_token_service)]


def get_oauth_service() -> OAuthService:
    return OAuthService(get_redis(), get_settings())


OAuthServiceDep = Annotated[OAuthService, Depends(get_oauth_service)]


def get_oauth_token_service(tx: UnitOfWorkDep) -> OAuthTokenService:
    return OAuthTokenService(tx.session, tx.oauth_tokens, tx.oauth_clients)


OAuthTokenServiceDep = Annotated[OAuthTokenService, Depends(get_oauth_token_service)]


def get_deck_service(tx: UnitOfWorkDep) -> DeckService:
    return DeckService(tx.session, tx.decks, tx.cards, get_settings())


def get_card_service(tx: UnitOfWorkDep) -> CardService:
    return CardService(
        tx.session, tx.cards, tx.card_reports, tx.jobs, tx.knowledge, tx.generations, tx.users
    )


DeckServiceDep = Annotated[DeckService, Depends(get_deck_service)]
CardServiceDep = Annotated[CardService, Depends(get_card_service)]


def get_job_service(tx: UnitOfWorkDep) -> JobService:
    return JobService(tx.session, tx.jobs, JobEvents(get_redis()))


JobServiceDep = Annotated[JobService, Depends(get_job_service)]


async def get_owned_job(job_id: int, user: CurrentUser, service: JobServiceDep) -> JobRead:
    return await service.get(job_id, user)


OwnedJob = Annotated[JobRead, Depends(get_owned_job)]


async def get_owned_deck(deck_id: int, user: CurrentUser, tx: UnitOfWorkDep) -> Deck:
    """Someone else's deck answers 404, never 403."""
    return found(await tx.decks.get_owned(deck_id, user.id), DECK_NOT_FOUND)


OwnedDeck = Annotated[Deck, Depends(get_owned_deck)]


def get_material_service(tx: UnitOfWorkDep) -> MaterialService:
    settings = get_settings()
    return MaterialService(
        tx.session, tx.documents, tx.jobs, BudgetService(tx.usage, settings), settings
    )


MaterialServiceDep = Annotated[MaterialService, Depends(get_material_service)]


def get_generation_service(tx: UnitOfWorkDep) -> GenerationService:
    settings = get_settings()
    return GenerationService(
        tx.session,
        tx.documents,
        tx.generations,
        tx.jobs,
        tx.cards,
        BudgetService(tx.usage, settings),
        settings,
    )


GenerationServiceDep = Annotated[GenerationService, Depends(get_generation_service)]


def get_problem_card_service(tx: UnitOfWorkDep) -> ProblemCardService:
    return ProblemCardService(tx.session, tx.problem_cards, tx.cards, tx.jobs, get_settings())


ProblemCardServiceDep = Annotated[ProblemCardService, Depends(get_problem_card_service)]


def get_tutor_service(tx: UnitOfWorkDep) -> TutorService:
    settings = get_settings()
    return TutorService(
        tx.session,
        tx.tutor,
        tx.cards,
        tx.jobs,
        BudgetService(tx.usage, settings),
        settings,
        RedisByteStore(get_redis()),
    )


TutorServiceDep = Annotated[TutorService, Depends(get_tutor_service)]


def get_study_service(tx: UnitOfWorkDep, problem_cards: ProblemCardServiceDep) -> StudyService:
    return StudyService(tx.session, tx.cards, problem_cards, tx.knowledge, tx.users)


StudyServiceDep = Annotated[StudyService, Depends(get_study_service)]
