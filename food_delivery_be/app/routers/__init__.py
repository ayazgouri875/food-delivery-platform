from app.routers.auth import router as auth_router
from app.routers.menu import router as menu_router
from app.routers.restaurants import router as restaurants_router
from app.routers.users import router as users_router

__all__ = [
    "auth_router",
    "users_router",
    "restaurants_router",
    "menu_router",
]
