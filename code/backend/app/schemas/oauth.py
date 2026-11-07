"""Bodies for the OAuth consent page and what's held in Redis between its steps."""

from pydantic import BaseModel

from app.schemas.common import UtcDatetime


class PendingRequest(BaseModel):
    """A client's checked /authorize request that waits for the user to approve it."""

    client_id: str
    client_name: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    code_challenge: str
    scopes: list[str]
    state: str | None
    resource: str | None


class ConsentRead(BaseModel):
    client_name: str  # chosen by whoever registered the client and shown next to the host
    redirect_host: str  # where the user goes next which the client can't fake


class ConsentDecision(BaseModel):
    approve: bool


class ConnectedApp(BaseModel):
    client_id: str
    name: str | None  # what the app called itself when it registered
    connected_at: UtcDatetime
    last_used_at: UtcDatetime | None


class ConsentResult(BaseModel):
    redirect_url: str  # back to the client with a code or an access_denied error
