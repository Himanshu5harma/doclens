"""FastAPI dependencies: verified identity, request session and current workspace membership."""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from doclens.access.tokens import (
    AuthenticationError,
    Identity,
    IdentityProviderUnavailable,
)
from doclens.db.models import Membership, Principal, Workspace

bearer = HTTPBearer(auto_error=False)


def get_identity(request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> Identity:
    if credentials is None:
        raise HTTPException(401, "Invalid or missing access token.", headers={"WWW-Authenticate": "Bearer"})
    try:
        return request.app.state.verifier.verify(credentials.credentials)
    except AuthenticationError:
        raise HTTPException(401, "Invalid or missing access token.", headers={"WWW-Authenticate": "Bearer"}) from None
    except IdentityProviderUnavailable:
        raise HTTPException(503, "Identity provider unavailable.") from None


def get_session(request: Request):
    # One session per request; closing rolls back any uncommitted read/failure.
    with request.app.state.sessions() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
IdentityDep = Annotated[Identity, Depends(get_identity)]


@dataclass(frozen=True)
class WorkspaceAccess:
    workspace_id: UUID
    principal_id: UUID
    role: str


def require_workspace(workspace_id: UUID, identity: IdentityDep, session: SessionDep) -> WorkspaceAccess:
    row = session.execute(
        select(Membership.principal_id, Membership.role)
        .join(Principal, Principal.id == Membership.principal_id)
        .join(Workspace, Workspace.id == Membership.workspace_id)
        .where(Workspace.id == workspace_id, Principal.issuer == identity.issuer,
               Principal.subject == identity.subject)
    ).one_or_none()
    if row is None:
        raise HTTPException(404, "Resource not found.")
    return WorkspaceAccess(workspace_id, row.principal_id, row.role)


AccessDep = Annotated[WorkspaceAccess, Depends(require_workspace)]
