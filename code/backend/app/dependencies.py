"""What routes can ask FastAPI for: services, and the signed-in user."""

from typing import Annotated

from fastapi import Cookie, Depends

from app.ai.knowledge.cache import RedisByteStore
from app.core.database import SessionDep
from app.core.errors import NotFound
from app.core.redis import get_redis
from app.core.settings import get_settings
from app.jobs.events import JobEvents
from app.models import Deck, User
from app.repositories.cards import CardRepository
from app.repositories.decks import DeckRepository
from app.repositories.documents import DocumentRepository
from app.repositories.generations import GenerationRepository
from app.repositories.jobs import JobRepository
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.problem_cards import ProblemCardRepository
from app.repositories.tutor import TutorRepository
from app.repositories.usage import UsageRepository
from app.repositories.users import UserRepository
from app.schemas.jobs import JobRead
from app.services.auth import AuthService
from app.services.budget import BudgetService
from app.services.cards import CardService
from app.services.decks import DECK_NOT_FOUND, DeckService
from app.services.generations import GenerationService
from app.services.jobs import JobService
from app.services.materials import MaterialService
from app.services.problem_cards import ProblemCardService
from app.services.study import StudyService
from app.services.tutor import TutorService

SESSION_COOKIE = "session"


def get_auth_service(session: SessionDep) -> AuthService:
    return AuthService(session, UserRepository(session), get_settings())


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
SessionToken = Annotated[str | None, Cookie(alias=SESSION_COOKIE)]


async def get_current_user(service: AuthServiceDep, token: SessionToken = None) -> User:
    return await service.user_for_token(token)


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_deck_service(session: SessionDep) -> DeckService:
    return DeckService(session, DeckRepository(session), CardRepository(session), get_settings())


def get_card_service(session: SessionDep) -> CardService:
    return CardService(
        session,
        CardRepository(session),
        JobRepository(session),
        KnowledgeRepository(session),
        GenerationRepository(session),
        UserRepository(session),
    )


DeckServiceDep = Annotated[DeckService, Depends(get_deck_service)]
CardServiceDep = Annotated[CardService, Depends(get_card_service)]


def get_job_service(session: SessionDep) -> JobService:
    return JobService(session, JobRepository(session), JobEvents(get_redis()))


JobServiceDep = Annotated[JobService, Depends(get_job_service)]


async def get_owned_job(job_id: int, user: CurrentUser, service: JobServiceDep) -> JobRead:
    return await service.get(job_id, user)


OwnedJob = Annotated[JobRead, Depends(get_owned_job)]


async def get_owned_deck(deck_id: int, user: CurrentUser, session: SessionDep) -> Deck:
    """Someone else's deck answers 404, never 403."""
    deck = await DeckRepository(session).get_owned(deck_id, user.id)
    if deck is None:
        raise NotFound(DECK_NOT_FOUND)
    return deck


OwnedDeck = Annotated[Deck, Depends(get_owned_deck)]


def get_material_service(session: SessionDep) -> MaterialService:
    settings = get_settings()
    return MaterialService(
        session,
        DocumentRepository(session),
        JobRepository(session),
        BudgetService(UsageRepository(session), settings),
        settings,
    )


MaterialServiceDep = Annotated[MaterialService, Depends(get_material_service)]


def get_generation_service(session: SessionDep) -> GenerationService:
    settings = get_settings()
    return GenerationService(
        session,
        DocumentRepository(session),
        GenerationRepository(session),
        JobRepository(session),
        CardRepository(session),
        BudgetService(UsageRepository(session), settings),
        settings,
    )


GenerationServiceDep = Annotated[GenerationService, Depends(get_generation_service)]


def get_problem_card_service(session: SessionDep) -> ProblemCardService:
    return ProblemCardService(
        session,
        ProblemCardRepository(session),
        CardRepository(session),
        JobRepository(session),
        get_settings(),
    )


ProblemCardServiceDep = Annotated[ProblemCardService, Depends(get_problem_card_service)]


def get_tutor_service(session: SessionDep) -> TutorService:
    settings = get_settings()
    return TutorService(
        session,
        TutorRepository(session),
        CardRepository(session),
        JobRepository(session),
        BudgetService(UsageRepository(session), settings),
        settings,
        RedisByteStore(get_redis()),
    )


TutorServiceDep = Annotated[TutorService, Depends(get_tutor_service)]


def get_study_service(session: SessionDep, problem_cards: ProblemCardServiceDep) -> StudyService:
    return StudyService(
        session,
        CardRepository(session),
        problem_cards,
        KnowledgeRepository(session),
        UserRepository(session),
    )


StudyServiceDep = Annotated[StudyService, Depends(get_study_service)]
