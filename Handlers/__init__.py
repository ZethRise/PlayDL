from aiogram import Router

from Handlers.errors import router as errors_router
from Handlers.links import router as links_router
from Handlers.start import router as start_router


def setup_routers() -> Router:
    router = Router(name="main")
    router.include_router(start_router)
    router.include_router(links_router)
    router.include_router(errors_router)
    return router
