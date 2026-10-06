from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.redis import delete_cache, delete_pattern, get_cache, set_cache
from app.dependencies.auth import get_current_user, require_role
from app.dependencies.database import get_db
from app.models.menu import MenuCategory, MenuItem
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.schemas.menu import MenuCategoryWithItems, MenuItemResponse, RestaurantFullMenuResponse
from app.schemas.restaurant import (
    RestaurantCreate,
    RestaurantResponse,
    RestaurantStatusUpdate,
    RestaurantToggleOpen,
    RestaurantUpdate,
)

router = APIRouter(prefix="/restaurants", tags=["Restaurants"])


@router.post(
    "/",
    response_model=RestaurantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new restaurant (Owner / Admin)"
)
def create_restaurant(
    restaurant_in: RestaurantCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role([UserRole.RESTAURANT, UserRole.ADMIN]))
):
    """
    Register a restaurant on the platform.
    - Owner is automatically set to the authenticated user.
    - Restaurant is created as `is_active=False` pending Admin verification (unless created by an Admin).
    """
    is_active = True if current_user.role == UserRole.ADMIN else False

    new_restaurant = Restaurant(
        name=restaurant_in.name,
        owner_id=current_user.id,
        address_line=restaurant_in.address_line,
        city=restaurant_in.city,
        latitude=restaurant_in.latitude,
        longitude=restaurant_in.longitude,
        is_active=is_active,
        is_open=True
    )
    db.add(new_restaurant)
    db.commit()
    db.refresh(new_restaurant)
    delete_pattern("restaurants:list:*")
    return new_restaurant


@router.get(
    "/",
    response_model=List[RestaurantResponse],
    summary="Discover restaurants with city and search filters"
)
def list_restaurants(
    response: Response,
    city: Optional[str] = Query(None, description="Filter by city name"),
    search: Optional[str] = Query(None, description="Search by restaurant name"),
    is_open_only: bool = Query(True, description="Only return currently open restaurants"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    Public restaurant discovery endpoint for customers.
    Only returns approved (`is_active=True`) restaurants.
    Uses Redis cache-aside with a 60-second TTL.
    """
    cache_key = f"restaurants:list:{city or 'all'}:{search or 'all'}:{is_open_only}:{skip}:{limit}"
    cached_list = get_cache(cache_key)
    if cached_list:
        response.headers["X-Cache"] = "HIT"
        return cached_list

    query = db.query(Restaurant).filter(Restaurant.is_active == True)

    if city:
        query = query.filter(Restaurant.city.ilike(f"%{city}%"))
    if search:
        query = query.filter(Restaurant.name.ilike(f"%{search}%"))
    if is_open_only:
        query = query.filter(Restaurant.is_open == True)

    results = query.offset(skip).limit(limit).all()
    serialized = [RestaurantResponse.model_validate(r).model_dump(mode="json") for r in results]
    set_cache(cache_key, serialized, ttl=60)
    response.headers["X-Cache"] = "MISS"
    return results


@router.get(
    "/{restaurant_id}",
    response_model=RestaurantResponse,
    summary="Get restaurant details"
)
def get_restaurant(restaurant_id: int, db: Session = Depends(get_db)):
    """
    Get detailed information about a single restaurant.
    """
    restaurant = db.query(Restaurant).filter(Restaurant.id == restaurant_id).first()
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


@router.get(
    "/{restaurant_id}/menu",
    response_model=RestaurantFullMenuResponse,
    summary="View complete restaurant menu with categories and items"
)
def get_restaurant_menu(
    restaurant_id: int,
    response: Response,
    db: Session = Depends(get_db)
):
    """
    Public customer menu view.
    Cache-Aside Pattern:
    1. Checks Redis for 'restaurant:{id}:menu'
    2. Cache HIT: returns cached JSON immediately (sub-millisecond latency)
    3. Cache MISS: queries PostgreSQL, serializes, writes to Redis with TTL, and returns
    """
    cache_key = f"restaurant:{restaurant_id}:menu"
    cached_menu = get_cache(cache_key)
    if cached_menu:
        response.headers["X-Cache"] = "HIT"
        return cached_menu

    restaurant = db.query(Restaurant).filter(Restaurant.id == restaurant_id).first()
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")

    categories = (
        db.query(MenuCategory)
        .filter(MenuCategory.restaurant_id == restaurant_id)
        .order_by(MenuCategory.display_order.asc())
        .all()
    )

    categories_with_items = []
    for cat in categories:
        items = (
            db.query(MenuItem)
            .filter(MenuItem.category_id == cat.id, MenuItem.is_available == True)
            .all()
        )
        cat_data = MenuCategoryWithItems(
            id=cat.id,
            restaurant_id=cat.restaurant_id,
            name=cat.name,
            display_order=cat.display_order,
            created_at=cat.created_at,
            items=[MenuItemResponse.model_validate(it) for it in items]
        )
        categories_with_items.append(cat_data)

    uncategorized = (
        db.query(MenuItem)
        .filter(
            MenuItem.restaurant_id == restaurant_id,
            MenuItem.category_id.is_(None),
            MenuItem.is_available == True
        )
        .all()
    )

    menu_response = RestaurantFullMenuResponse(
        restaurant=RestaurantResponse.model_validate(restaurant),
        categories=categories_with_items,
        uncategorized_items=[MenuItemResponse.model_validate(it) for it in uncategorized]
    )

    # Store in Redis with TTL (default: 300s / 5 minutes)
    set_cache(cache_key, menu_response.model_dump(mode="json"), ttl=settings.CACHE_TTL_SECONDS)
    response.headers["X-Cache"] = "MISS"
    return menu_response


@router.patch(
    "/{restaurant_id}/status",
    response_model=RestaurantResponse,
    summary="Approve or block restaurant (Admin only)"
)
def update_restaurant_status(
    restaurant_id: int,
    status_in: RestaurantStatusUpdate,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_role([UserRole.ADMIN]))
):
    """
    Admin control to activate (approve) or deactivate a restaurant.
    """
    restaurant = db.query(Restaurant).filter(Restaurant.id == restaurant_id).first()
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")

    restaurant.is_active = status_in.is_active
    db.commit()
    db.refresh(restaurant)

    # Invalidate cached menu and listings
    delete_cache(f"restaurant:{restaurant_id}:menu")
    delete_pattern("restaurants:list:*")
    return restaurant


@router.patch(
    "/{restaurant_id}/toggle-open",
    response_model=RestaurantResponse,
    summary="Open or close restaurant for orders (Owner / Admin)"
)
def toggle_restaurant_open(
    restaurant_id: int,
    toggle_in: RestaurantToggleOpen,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Allows the restaurant owner to toggle whether their kitchen is currently taking orders.
    """
    restaurant = db.query(Restaurant).filter(Restaurant.id == restaurant_id).first()
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")

    if current_user.role != UserRole.ADMIN and restaurant.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to modify this restaurant."
        )

    restaurant.is_open = toggle_in.is_open
    db.commit()
    db.refresh(restaurant)

    # Invalidate cached menu and listings
    delete_cache(f"restaurant:{restaurant_id}:menu")
    delete_pattern("restaurants:list:*")
    return restaurant
