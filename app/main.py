"""
ArenaIQ — FastAPI application factory, HTTP endpoints, middleware, and static UI.

This module is the ASGI entry point for the ArenaIQ backend. It exports a
module-level ``app`` instance created by :func:`create_app` for use with
uvicorn (``uvicorn app.main:app``), and exposes :func:`create_app` for use
by the test suite with custom :class:`~app.config.Settings`.

Endpoints:
    * ``GET  /``               — Serves the accessible single-page UI (index.html).
    * ``GET  /health``         — Liveness probe; returns ``{"status": "ok"}``.
    * ``POST /api/assist``     — Context-aware routing assistance (rate-limited).
    * ``GET  /api/stadium``    — Zone/facility metadata for the frontend UI.
    * ``GET  /static/{file}``  — Mounted static file server for CSS/JS assets.

Security:
    * CORS is restricted to an explicit allow-list plus a Vercel subdomain
      regex. Wildcard origins are never used.
    * HTTP security headers (CSP, X-Frame-Options, etc.) are injected by
      a middleware layer on every response.
    * The ``/api/assist`` endpoint is protected by a per-IP token-bucket
      rate limiter; excessive callers receive HTTP 429.
    * All user input is validated by Pydantic and sanitized by
      :func:`~app.services.security.sanitize_text` before reaching any
      service layer or LLM.

Typical usage::

    # Production — uvicorn reads the module-level ``app`` directly:
    # uvicorn app.main:app --host 0.0.0.0 --port 8000

    # Tests — use create_app with an injected Settings instance:
    from app.main import create_app
    from app.config import Settings
    app = create_app(Settings(gemini_api_key=None))
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.logging_conf import get_logger
from app.models.schemas import (
    AccessibilityNeed,
    AssistResponse,
    DestinationIntent,
    HealthResponse,
    Language,
    UserContext,
)
from app.services.context_engine import RouteNotFound, run_assist
from app.services.llm import get_llm_client
from app.services.security import RateLimiter
from app.services.stadium_data import Stadium, get_stadium

logger = get_logger("arenaiq")

_STATIC_DIR: Path = Path(__file__).resolve().parent / "static"

# Security response headers applied to every HTTP response by the middleware layer.
# CSP disallows inline scripts and restricts resource origins to ``'self'`` only.
_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"
    ),
}


def _stadium_metadata(stadium: Stadium) -> dict[str, Any]:
    """Serialize zones, facilities, and enum vocabularies for the frontend.

    Converts the in-memory :class:`~app.services.stadium_data.Stadium`
    into a plain JSON-serializable dict used by the ``GET /api/stadium``
    endpoint. Zone and facility names/landmarks are returned as localized
    maps (``{"en": ..., "es": ..., "fr": ...}``) so the frontend can
    render the correct language client-side without additional API calls.

    Args:
        stadium: The loaded :class:`~app.services.stadium_data.Stadium`
            singleton from ``app.state.stadium``.

    Returns:
        A JSON-serializable dict with keys ``stadium``, ``zones``,
        ``facilities``, ``intents``, ``languages``, and
        ``accessibility_needs``.
    """
    return {
        "stadium": {
            "name": stadium.name,
            "fifa_name": stadium.fifa_name,
            "city": stadium.city,
            "capacity": stadium.capacity,
        },
        # ``name``/``landmark`` are localized maps ({en, es, fr}); the UI picks the language.
        "zones": [
            {"id": z.id, "name": z.names, "type": z.type, "level": z.level}
            for z in stadium.zones.values()
        ],
        "facilities": [
            {
                "id": f.id,
                "name": f.names,
                "type": f.type,
                "zone": f.zone,
                "accessible": f.accessible,
                "landmark": f.landmarks,
            }
            for f in stadium.facilities
        ],
        "intents": [i.value for i in DestinationIntent],
        "languages": [lang.value for lang in Language],
        "accessibility_needs": [n.value for n in AccessibilityNeed],
    }


def _rate_limit_dependency(request: Request) -> None:
    """FastAPI dependency that enforces per-IP rate limiting on protected endpoints.

    Retrieves the shared :class:`~app.services.security.RateLimiter` from
    ``app.state`` and checks whether the requesting IP has tokens remaining.
    Rejected requests receive HTTP 429 with a ``Retry-After`` header.

    Args:
        request: The incoming FastAPI :class:`fastapi.Request` object,
            used to access ``app.state.rate_limiter`` and the client IP.

    Returns:
        None if the request is within the rate limit.

    Raises:
        fastapi.HTTPException: With status 429 and ``Retry-After`` header
            when the client has exceeded its token-bucket allowance.
    """
    limiter: RateLimiter = request.app.state.rate_limiter
    client_ip = request.client.host if request.client else "unknown"
    allowed, retry_after = limiter.check(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Please slow down.",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory that builds and configures the FastAPI ASGI application.

    Initialises all process-wide singletons (stadium data, LLM client, rate
    limiter) on the ``app.state``, registers CORS and security-header
    middleware, registers the exception handler for :class:`RouteNotFound`,
    and mounts all route handlers and the static file server.

    Accepting an explicit ``settings`` argument allows the test suite to
    inject a custom :class:`~app.config.Settings` instance (e.g. with
    ``gemini_api_key=None``) without modifying environment variables.

    Args:
        settings: Optional :class:`~app.config.Settings` instance. If
            ``None``, the process-wide cached instance from
            :func:`~app.config.get_settings` is used.

    Returns:
        A fully configured :class:`fastapi.FastAPI` application instance
        ready to be served by an ASGI server such as uvicorn.
    """
    settings = settings or get_settings()

    app = FastAPI(
        title="ArenaIQ",
        description="Multilingual, accessible stadium assistant for FIFA World Cup 2026.",
        version="1.0.0",
    )

    # Attach process-wide singletons to app.state for injection into route handlers.
    app.state.settings = settings
    app.state.stadium = get_stadium()
    app.state.llm = get_llm_client(settings)
    app.state.rate_limiter = RateLimiter(
        settings.rate_limit_capacity, settings.rate_limit_refill_per_sec
    )

    # Restrictive CORS: explicit allow-list (localhost dev) plus a Vercel subdomain
    # regex for production deployments. Wildcard origins are never permitted.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_origin_regex=r"^https://.*\.vercel\.app$",
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next: Callable) -> Response:
        """Inject security headers into every HTTP response.

        Uses ``setdefault`` so that route handlers can override individual
        headers for specific responses without this middleware overwriting them.

        Args:
            request: The incoming HTTP request (passed through unchanged).
            call_next: The next middleware or route handler in the ASGI stack.

        Returns:
            The HTTP response with all ``_SECURITY_HEADERS`` applied.
        """
        response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response

    @app.exception_handler(RouteNotFound)
    async def _route_not_found_handler(request: Request, exc: RouteNotFound) -> JSONResponse:
        """Convert a :class:`RouteNotFound` domain exception to an HTTP 404 response.

        Args:
            request: The incoming HTTP request (unused but required by FastAPI).
            exc: The :class:`RouteNotFound` exception carrying a descriptive message.

        Returns:
            A :class:`fastapi.responses.JSONResponse` with status 404 and
            ``{"detail": <exception message>}`` body.
        """
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        """Liveness probe endpoint — returns OK without touching the LLM or database.

        Returns:
            A :class:`~app.models.schemas.HealthResponse` with ``status="ok"``.
        """
        return HealthResponse(status="ok")

    @app.get("/api/stadium", tags=["data"])
    async def stadium_metadata(request: Request) -> dict[str, Any]:
        """Return serialized stadium zone, facility, and vocabulary metadata.

        Used by the frontend on page load to populate the location and
        destination selectors with localized options.

        Args:
            request: The incoming HTTP request providing access to
                ``app.state.stadium``.

        Returns:
            A JSON-serializable dict produced by :func:`_stadium_metadata`.
        """
        return _stadium_metadata(request.app.state.stadium)

    @app.post(
        "/api/assist",
        response_model=AssistResponse,
        dependencies=[Depends(_rate_limit_dependency)],
        tags=["assist"],
    )
    async def assist(ctx: UserContext, request: Request) -> AssistResponse:
        """Run the rules engine and optional LLM to produce a stadium navigation response.

        The rate-limit dependency is evaluated before this handler executes.
        Structured context is passed to :func:`~app.services.context_engine.run_assist`
        which resolves routing facts deterministically before engaging the LLM.

        Privacy note: only non-identifying signals (zone IDs, intents, crowd
        level, LLM usage flag) are logged — the raw ``question`` is never
        written to the log stream.

        Args:
            ctx: The validated :class:`~app.models.schemas.UserContext`
                deserialized from the POST request body.
            request: The incoming HTTP request providing access to
                ``app.state.stadium`` and ``app.state.llm``.

        Returns:
            A fully populated :class:`~app.models.schemas.AssistResponse`.

        Raises:
            RouteNotFound: When no facility/route satisfies the request
                constraints (caught by ``_route_not_found_handler`` → 404).
            fastapi.HTTPException: 429 when the IP rate limit is exceeded
                (raised by ``_rate_limit_dependency`` before this handler).
        """
        stadium: Stadium = request.app.state.stadium
        llm = request.app.state.llm
        response = await run_assist(ctx, stadium, llm)
        # Privacy-preserving log: intents, zones, outcomes only — never the question.
        logger.info(
            "assist location=%s intent=%s needs=%s crowd=%s used_llm=%s",
            ctx.current_location,
            ctx.destination_intent.value,
            "+".join(n.value for n in ctx.accessibility_needs),
            response.crowd_level.value,
            response.used_llm,
        )
        return response

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        """Serve the ArenaIQ single-page application HTML shell.

        Returns:
            A :class:`fastapi.responses.FileResponse` streaming ``index.html``
            from the static directory.
        """
        return FileResponse(_STATIC_DIR / "index.html")

    # Mount the static file server for CSS/JS assets after the explicit ``/`` route
    # so that ``/`` itself is handled by the ``index`` handler above.
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    return app


# Module-level ASGI application instance for ``uvicorn app.main:app``.
app = create_app()
