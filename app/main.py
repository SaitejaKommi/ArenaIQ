"""
ArenaIQ — FastAPI application factory and HTTP endpoints.

This module is the composition root for the entire ASGI application.
It wires together all service singletons, middleware, exception handlers,
and route definitions into a single configured :class:`fastapi.FastAPI` instance.

Startup lifecycle
-----------------
When ``create_app()`` is called (at module load time for uvicorn), the
following steps execute in order:

1. ``_init_state(app, conf)`` — constructs and attaches process-wide
   singletons (stadium fixture, LLM client, rate limiter) onto ``app.state``
   so all request handlers share the same objects without global mutation.

2. ``_register_middleware(app, conf)`` — attaches:
   - ``CORSMiddleware`` allowing the configured origins plus any
     ``*.vercel.app`` domain for preview deployments.
   - An ``add_security_headers`` HTTP middleware that injects ``X-Frame-Options``,
     ``Content-Security-Policy``, and related headers on every response.

3. ``_register_handlers(app)`` — attaches a custom exception handler that
   translates :class:`~app.services.context_engine.RouteNotFound` exceptions
   into HTTP 404 JSON responses.

4. ``_register_routes(app)`` — registers the four HTTP endpoints:
   ``GET /health``, ``GET /api/stadium``, ``POST /api/assist``, ``GET /``.
   A ``/static`` mount for CSS/JS assets is added last.

Security model
--------------
Every response carries a strict Content-Security-Policy header
(``default-src 'self'``) enforced by the ``add_security_headers`` middleware.
Incoming requests to ``POST /api/assist`` pass through a token-bucket
:class:`~app.services.security.RateLimiter` injected as a FastAPI dependency,
returning HTTP 429 when the per-IP bucket is exhausted.

Mount points
------------
- ``/static`` → serves ``app/static/`` files (CSS, JS).
- ``/``       → serves ``app/static/index.html`` directly (SPA root).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
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

_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"
    ),
}


def _build_metadata_zones(stadium: Stadium) -> list[dict[str, Any]]:
    """Build the zones array for the ``/api/stadium`` metadata response.

    Args:
        stadium: The loaded :class:`~app.services.stadium_data.Stadium` model.

    Returns:
        A list of dicts, each containing ``id``, ``name``, ``type``, and
        ``level`` for one zone in the stadium.

    Raises:
        None

    Example:
        >>> zones = _build_metadata_zones(get_stadium())
        >>> zones[0].keys()
        dict_keys(['id', 'name', 'type', 'level'])
    """
    return [
        {"id": z.id, "name": z.names, "type": z.type, "level": z.level}
        for z in stadium.zones.values()
    ]


def _build_metadata_facs(stadium: Stadium) -> list[dict[str, Any]]:
    """Build the facilities array for the ``/api/stadium`` metadata response.

    Args:
        stadium: The loaded :class:`~app.services.stadium_data.Stadium` model.

    Returns:
        A list of dicts, each containing ``id``, ``name``, ``type``, ``zone``,
        ``accessible``, and ``landmark`` for one facility.

    Raises:
        None

    Example:
        >>> facs = _build_metadata_facs(get_stadium())
        >>> facs[0].keys()
        dict_keys(['id', 'name', 'type', 'zone', 'accessible', 'landmark'])
    """
    return [
        {
            "id": f.id, "name": f.names, "type": f.type,
            "zone": f.zone, "accessible": f.accessible, "landmark": f.landmarks,
        }
        for f in stadium.facilities
    ]


def _stadium_metadata(stadium: Stadium) -> dict[str, Any]:
    """Serialize zones, facilities, and enum vocabularies for the frontend.

    Args:
        stadium: The loaded stadium model.

    Returns:
        JSON-serializable metadata dict with keys ``stadium``, ``zones``,
        ``facilities``, ``intents``, ``languages``, and ``accessibility_needs``.

    Raises:
        None

    Example:
        >>> meta = _stadium_metadata(get_stadium())
        >>> set(meta.keys())
        {'stadium', 'zones', 'facilities', 'intents', 'languages', 'accessibility_needs'}
    """
    return {
        "stadium": {
            "name": stadium.name, "fifa_name": stadium.fifa_name,
            "city": stadium.city, "capacity": stadium.capacity,
        },
        "zones": _build_metadata_zones(stadium),
        "facilities": _build_metadata_facs(stadium),
        "intents": [i.value for i in DestinationIntent],
        "languages": [lang.value for lang in Language],
        "accessibility_needs": [n.value for n in AccessibilityNeed],
    }


def _rate_limit_dependency(request: Request) -> None:
    """FastAPI dependency enforcing per-IP rate limiting.

    Args:
        request: Incoming FastAPI request object used to extract the client IP.

    Returns:
        None (raises HTTPException if the bucket is exhausted).

    Raises:
        HTTPException: HTTP 429 status with ``Retry-After`` header when the
            client's token bucket is empty.

    Example:
        >>> Depends(_rate_limit_dependency)
    """
    limiter: RateLimiter = request.app.state.rate_limiter
    client_ip: str = request.client.host if request.client else "unknown"
    allowed, retry_after = limiter.check(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=429, detail="Rate limit exceeded.",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )


def _init_state(app: FastAPI, settings: Settings) -> None:
    """Initialize process-wide singletons and attach them to ``app.state``.

    All heavy objects (stadium graph, LLM client, rate limiter) are
    constructed once here so that route handlers can access them via
    ``request.app.state`` without triggering repeated initialisation.

    Args:
        app: The :class:`fastapi.FastAPI` instance to attach state onto.
        settings: Application settings providing API keys and limits.

    Returns:
        None

    Raises:
        None

    Example:
        >>> app = FastAPI()
        >>> _init_state(app, get_settings())
        >>> hasattr(app.state, "stadium")
        True
    """
    app.state.settings = settings
    app.state.stadium = get_stadium()
    app.state.llm = get_llm_client(settings)
    app.state.rate_limiter = RateLimiter(
        settings.rate_limit_capacity, settings.rate_limit_refill_per_sec
    )


def _register_middleware(app: FastAPI, settings: Settings) -> None:
    """Attach CORS and security-header middleware to the application.

    Registers two middleware layers:
    1. :class:`fastapi.middleware.cors.CORSMiddleware` allowing the origins
       specified in settings plus any ``*.vercel.app`` preview domain.
    2. An ``add_security_headers`` HTTP middleware that injects hardened
       headers (CSP, X-Frame-Options, etc.) on every outgoing response.

    Args:
        app: The :class:`fastapi.FastAPI` instance to register middleware on.
        settings: Application settings providing the CORS allow-list.

    Returns:
        None

    Raises:
        None

    Example:
        >>> app = FastAPI()
        >>> _register_middleware(app, get_settings())
    """
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.allowed_origins,
        allow_origin_regex=r"^https://.*\.vercel\.app$", allow_credentials=False,
        allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def add_security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Inject hardened HTTP security headers on every outgoing response.

        Calls the next middleware/handler and then sets all headers defined
        in ``_SECURITY_HEADERS`` using ``setdefault`` so that route handlers
        can override individual headers if needed.

        Args:
            request: The incoming HTTP request.
            call_next: The next handler in the middleware chain.

        Returns:
            The HTTP response with security headers added.

        Raises:
            None
        """
        res: Response = await call_next(request)
        for h, v in _SECURITY_HEADERS.items():
            res.headers.setdefault(h, v)
        return res


def _register_handlers(app: FastAPI) -> None:
    """Attach custom exception handlers to translate domain errors to HTTP responses.

    Args:
        app: The :class:`fastapi.FastAPI` instance to register handlers on.

    Returns:
        None

    Raises:
        None

    Example:
        >>> app = FastAPI()
        >>> _register_handlers(app)
    """
    @app.exception_handler(RouteNotFound)
    async def _route_not_found_handler(request: Request, exc: RouteNotFound) -> JSONResponse:
        """Translate a RouteNotFound domain exception into an HTTP 404 response.

        Args:
            request: The incoming HTTP request (unused, required by FastAPI signature).
            exc: The :class:`~app.services.context_engine.RouteNotFound` exception.

        Returns:
            A :class:`fastapi.responses.JSONResponse` with status 404 and
            a ``detail`` key containing the exception message.

        Raises:
            None
        """
        return JSONResponse(status_code=404, content={"detail": str(exc)})


def _register_routes(app: FastAPI) -> None:
    """Register all HTTP route handlers onto the FastAPI application.

    Defines four endpoints:
    - ``GET /health`` — liveness probe.
    - ``GET /api/stadium`` — static stadium metadata for the frontend.
    - ``POST /api/assist`` — main navigation endpoint (rate-limited).
    - ``GET /`` — serves the SPA ``index.html``.

    Args:
        app: The :class:`fastapi.FastAPI` instance to register routes on.

    Returns:
        None

    Raises:
        None

    Example:
        >>> app = FastAPI()
        >>> _register_routes(app)
    """
    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        """Liveness probe endpoint.

        Returns:
            :class:`~app.models.schemas.HealthResponse` with ``status='ok'``
            confirming the server is running.

        Raises:
            None
        """
        return HealthResponse(status="ok")

    @app.get("/api/stadium", tags=["data"])
    async def stadium_metadata(request: Request) -> dict[str, Any]:
        """Return static stadium metadata used to populate the frontend dropdowns.

        Returns:
            A JSON dict containing ``stadium`` info, ``zones`` list, ``facilities``
            list, and the supported enum vocabularies (``intents``, ``languages``,
            ``accessibility_needs``).

        Raises:
            None
        """
        return _stadium_metadata(request.app.state.stadium)

    @app.post(
        "/api/assist",
        response_model=AssistResponse,
        dependencies=[Depends(_rate_limit_dependency)],
        tags=["assist"],
    )
    async def assist(ctx: UserContext, request: Request) -> AssistResponse:
        """Context-driven navigation endpoint — the core ArenaIQ functionality.

        Validates the incoming :class:`~app.models.schemas.UserContext`,
        runs the deterministic rules engine, phrases the result via the LLM
        client or offline templates, and returns the fully grounded response.

        Args:
            ctx: Validated user context from the request body.
            request: FastAPI request object used to access ``app.state``.

        Returns:
            :class:`~app.models.schemas.AssistResponse` containing the answer,
            route steps, facility info, crowd level, and LLM attribution flag.

        Raises:
            HTTPException: 422 if the request body fails Pydantic validation.
            HTTPException: 429 if the rate limit is exceeded.
            JSONResponse(404): If no route or facility matches the request.
        """
        stadium: Stadium = request.app.state.stadium
        res: AssistResponse = await run_assist(ctx, stadium, request.app.state.llm)
        logger.info(
            "assist location=%s intent=%s needs=%s crowd=%s used_llm=%s",
            ctx.current_location, ctx.destination_intent.value,
            "+".join(n.value for n in ctx.accessibility_needs),
            res.crowd_level.value, res.used_llm,
        )
        return res

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        """Serve the ArenaIQ single-page application HTML entry point.

        Returns:
            :class:`fastapi.responses.FileResponse` streaming ``index.html``
            from the static directory.

        Raises:
            None
        """
        return FileResponse(_STATIC_DIR / "index.html")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI ASGI application.

    Args:
        settings: Optional custom :class:`~app.config.Settings` instance.
            Defaults to the cached singleton from :func:`~app.config.get_settings`.

    Returns:
        A fully configured :class:`fastapi.FastAPI` instance ready for
        serving with uvicorn.

    Raises:
        None

    Example:
        >>> app = create_app()
        >>> type(app).__name__
        'FastAPI'
    """
    conf: Settings = settings or get_settings()
    app = FastAPI(title="ArenaIQ", version="1.0.0")

    _init_state(app, conf)
    _register_middleware(app, conf)
    _register_handlers(app)
    _register_routes(app)

    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
    return app


app = create_app()
