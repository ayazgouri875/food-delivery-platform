from app.routers.address import router as address_router
from app.routers.auth import router as auth_router
from app.routers.cart import router as cart_router
from app.routers.menu import router as menu_router
from app.routers.orders import router as orders_router
from app.routers.payments import router as payments_router
from app.routers.restaurants import router as restaurants_router
from app.routers.users import router as users_router

__all__ = [
    "auth_router",
    "users_router",
    "restaurants_router",
    "menu_router",
    "cart_router",
    "address_router",
    "orders_router",
    "payments_router",
]
