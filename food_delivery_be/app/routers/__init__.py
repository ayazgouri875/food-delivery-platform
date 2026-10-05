from app.routers.address import router as address_router
from app.routers.auth import router as auth_router
from app.routers.cart import router as cart_router
from app.routers.menu import router as menu_router
from app.routers.restaurants import router as restaurants_router
from app.routers.users import router as users_router

__all__ = [
    "auth_router",
    "users_router",
    "restaurants_router",
    "menu_router",
    "cart_router",
    "address_router",
]
