from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.redis import delete_cache
from app.dependencies.auth import get_current_user
from app.dependencies.database import get_db
from app.models.menu import MenuCategory, MenuItem
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.schemas.menu import (
    MenuCategoryCreate,
    MenuCategoryResponse,
    MenuItemAvailabilityUpdate,
    MenuItemCreate,
    MenuItemResponse,
    MenuItemUpdate,
)

router = APIRouter(tags=["Menu Management"])


def _verify_restaurant_owner(restaurant_id: int, current_user: User, db: Session) -> Restaurant:
    """Helper to verify that the current user is the owner of the restaurant or an admin."""
    restaurant = db.query(Restaurant).filter(Restaurant.id == restaurant_id).first()
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    if current_user.role != UserRole.ADMIN and restaurant.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to manage this restaurant's menu."
        )
    return restaurant


# Category Endpoints
@router.post(
    "/restaurants/{restaurant_id}/categories",
    response_model=MenuCategoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a menu category (Owner / Admin)"
)
def create_category(
    restaurant_id: int,
    category_in: MenuCategoryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _verify_restaurant_owner(restaurant_id, current_user, db)

    new_cat = MenuCategory(
        restaurant_id=restaurant_id,
        name=category_in.name,
        display_order=category_in.display_order
    )
    db.add(new_cat)
    db.commit()
    db.refresh(new_cat)
    delete_cache(f"restaurant:{restaurant_id}:menu")
    return new_cat


@router.get(
    "/restaurants/{restaurant_id}/categories",
    response_model=List[MenuCategoryResponse],
    summary="List all categories of a restaurant"
)
def list_categories(restaurant_id: int, db: Session = Depends(get_db)):
    return (
        db.query(MenuCategory)
        .filter(MenuCategory.restaurant_id == restaurant_id)
        .order_by(MenuCategory.display_order.asc())
        .all()
    )


# Menu Item Endpoints
@router.post(
    "/restaurants/{restaurant_id}/items",
    response_model=MenuItemResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a menu item to a restaurant (Owner / Admin)"
)
def create_menu_item(
    restaurant_id: int,
    item_in: MenuItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _verify_restaurant_owner(restaurant_id, current_user, db)

    # Validate category belongs to this restaurant if provided
    if item_in.category_id:
        category = db.query(MenuCategory).filter(
            MenuCategory.id == item_in.category_id,
            MenuCategory.restaurant_id == restaurant_id
        ).first()
        if not category:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Category does not belong to this restaurant."
            )

    new_item = MenuItem(
        restaurant_id=restaurant_id,
        category_id=item_in.category_id,
        name=item_in.name,
        description=item_in.description,
        price=item_in.price,
        is_available=item_in.is_available,
        is_veg=item_in.is_veg,
        stock_count=item_in.stock_count
    )
    db.add(new_item)
    db.commit()
    db.refresh(new_item)
    delete_cache(f"restaurant:{restaurant_id}:menu")
    return new_item


@router.get(
    "/restaurants/{restaurant_id}/items",
    response_model=List[MenuItemResponse],
    summary="List all items of a restaurant"
)
def list_menu_items(restaurant_id: int, db: Session = Depends(get_db)):
    return db.query(MenuItem).filter(MenuItem.restaurant_id == restaurant_id).all()


@router.patch(
    "/menu/items/{item_id}",
    response_model=MenuItemResponse,
    summary="Update menu item details (Owner / Admin)"
)
def update_menu_item(
    item_id: int,
    item_in: MenuItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu item not found")

    _verify_restaurant_owner(item.restaurant_id, current_user, db)

    update_data = item_in.model_dump(exclude_unset=True)
    if "category_id" in update_data and update_data["category_id"] is not None:
        cat = db.query(MenuCategory).filter(
            MenuCategory.id == update_data["category_id"],
            MenuCategory.restaurant_id == item.restaurant_id
        ).first()
        if not cat:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid category ID")

    for field, val in update_data.items():
        setattr(item, field, val)

    db.commit()
    db.refresh(item)
    delete_cache(f"restaurant:{item.restaurant_id}:menu")
    return item


@router.patch(
    "/menu/items/{item_id}/availability",
    response_model=MenuItemResponse,
    summary="Toggle menu item availability in-stock / out-of-stock (Owner / Admin)"
)
def toggle_item_availability(
    item_id: int,
    avail_in: MenuItemAvailabilityUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu item not found")

    _verify_restaurant_owner(item.restaurant_id, current_user, db)

    item.is_available = avail_in.is_available
    db.commit()
    db.refresh(item)
    delete_cache(f"restaurant:{item.restaurant_id}:menu")
    return item


@router.delete(
    "/menu/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a menu item (Owner / Admin)"
)
def delete_menu_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu item not found")

    _verify_restaurant_owner(item.restaurant_id, current_user, db)

    restaurant_id = item.restaurant_id
    db.delete(item)
    db.commit()
    delete_cache(f"restaurant:{restaurant_id}:menu")
    return None
