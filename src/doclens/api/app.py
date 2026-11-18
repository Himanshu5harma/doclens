"""FastAPI application factory plus workspace/source ownership routes; no request-time fetching."""

import logging
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from doclens.access.tokens import TokenVerifier
from doclens.api.deps import AccessDep, IdentityDep, SessionDep
from doclens.api.ingestion import router as ingestion_router
from doclens.api.schemas import SourceCreate, SourceRead, WorkspaceRead
from doclens.api.search import router as search_router
from doclens.db.models import Membership, Principal, RegisteredSource, Workspace
from doclens.ingestion.artifacts import ArtifactStore
from doclens.settings import ServiceSettings

logger = logging.getLogger("doclens.service")


def create_app(settings: ServiceSettings | None = None, *, verifier: TokenVerifier | None = None) -> FastAPI:
    try:
        settings = settings or ServiceSettings()
    except ValidationError:
        raise ValueError("Invalid DocLens service settings; check DOCLENS_DATABASE_URL and OIDC configuration.") from None
    engine = create_engine(
        settings.database_url.get_secret_value(), pool_pre_ping=True, hide_parameters=True,
        connect_args={"connect_timeout": 5},
    )

    @asynccontextmanager
    async def lifespan(app):
        yield
        engine.dispose()

    app = FastAPI(title="DocLens source service", version="1", lifespan=lifespan)
    app.state.sessions = sessionmaker(engine, expire_on_commit=False)
    app.state.verifier = verifier or TokenVerifier(settings)
    app.state.settings = settings
    app.state.artifacts = ArtifactStore(settings.artifact_root)

    @app.middleware("http")
    async def safe_request_summary(request, call_next):
        response = await call_next(request)
        route = request.scope.get("route")
        logger.info("request method=%s route=%s status=%s", request.method,
                    getattr(route, "path", "unmatched"), response.status_code)
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        # FastAPI's default includes rejected input values, potentially secrets.
        return JSONResponse(status_code=422, content={"detail": "Invalid request."})

    @app.exception_handler(SQLAlchemyError)
    async def database_failure(request, error):
        return JSONResponse(status_code=503, content={"detail": "Source service database unavailable."})

    @app.get("/api/v1/workspaces", response_model=list[WorkspaceRead])
    def list_workspaces(identity: IdentityDep, session: SessionDep,
                        limit: Annotated[int, Query(ge=1, le=100)] = 50,
                        offset: Annotated[int, Query(ge=0, le=100_000)] = 0):
        rows = session.execute(
            select(Workspace, Membership.role)
            .join(Membership, Membership.workspace_id == Workspace.id)
            .join(Principal, Principal.id == Membership.principal_id)
            .where(Principal.issuer == identity.issuer, Principal.subject == identity.subject)
            .order_by(Workspace.id).offset(offset).limit(limit)
        ).all()
        return [WorkspaceRead(id=w.id, slug=w.slug, name=w.name, role=role) for w, role in rows]

    @app.get("/api/v1/workspaces/{workspace_id}/sources", response_model=list[SourceRead])
    def list_sources(access: AccessDep, session: SessionDep,
                     limit: Annotated[int, Query(ge=1, le=100)] = 50,
                     offset: Annotated[int, Query(ge=0, le=100_000)] = 0):
        return session.scalars(
            select(RegisteredSource).where(RegisteredSource.workspace_id == access.workspace_id)
            .order_by(RegisteredSource.id).offset(offset).limit(limit)
        ).all()

    @app.get("/api/v1/workspaces/{workspace_id}/sources/{source_id}", response_model=SourceRead)
    def get_source(source_id: UUID, access: AccessDep, session: SessionDep):
        source = session.scalar(select(RegisteredSource).where(
            RegisteredSource.id == source_id, RegisteredSource.workspace_id == access.workspace_id,
        ))
        if source is None:
            raise HTTPException(404, "Resource not found.")
        return source

    @app.post("/api/v1/workspaces/{workspace_id}/sources", response_model=SourceRead, status_code=201)
    def register_source(body: SourceCreate, access: AccessDep, session: SessionDep):
        if access.role not in ("owner", "editor"):
            raise HTTPException(403, "Source registration requires owner or editor membership.")
        source = RegisteredSource(
            **body.model_dump(), workspace_id=access.workspace_id, created_by=access.principal_id,
        )
        session.add(source)
        try:
            session.commit()  # Commit before returning a success response.
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, "Source registration conflicts with existing data.") from None
        return source

    app.include_router(ingestion_router)
    app.include_router(search_router)
    return app
