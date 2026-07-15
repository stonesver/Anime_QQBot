from collections.abc import Callable

from fastapi import FastAPI, Response, status


def create_health_app(is_ready: Callable[[], bool] = lambda: True) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready(response: Response) -> dict[str, str]:
        if not is_ready():
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "not_ready"}
        return {"status": "ok"}

    return app
