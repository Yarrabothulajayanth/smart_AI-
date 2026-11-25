from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Category, Product
from app.schemas import CategoryCreate, CategoryRead, CategoryUpdate

router = APIRouter(prefix="/categories", tags=["Categories"])


def _category_name_conflict(error: IntegrityError) -> bool:
    return "categories.name" in str(error.orig)


@router.post(
    "/",
    response_model=CategoryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a category",
    description="Create a product category. Category names must be unique.",
    responses={409: {"description": "A category with this name already exists."}},
)
def create_category(
    payload: CategoryCreate, db: Session = Depends(get_db)
) -> Category:
    existing = db.scalar(select(Category).where(Category.name == payload.name))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A category with this name already exists.",
        )

    category = Category(**payload.model_dump())
    db.add(category)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        if _category_name_conflict(error):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A category with this name already exists.",
            ) from error
        raise
    db.refresh(category)
    return category


@router.get(
    "/",
    response_model=list[CategoryRead],
    summary="List categories",
    description="Return all product categories, ordered by name.",
)
def list_categories(db: Session = Depends(get_db)) -> list[Category]:
    return list(db.scalars(select(Category).order_by(Category.name)).all())


@router.put(
    "/{category_id}",
    response_model=CategoryRead,
    summary="Update a category",
    description="Replace a category's name and description.",
    responses={
        404: {"description": "Category not found."},
        409: {"description": "A category with this name already exists."},
    },
)
def update_category(
    category_id: int,
    payload: CategoryUpdate,
    db: Session = Depends(get_db),
) -> Category:
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Category not found."
        )

    duplicate = db.scalar(
        select(Category).where(
            Category.name == payload.name,
            Category.id != category_id,
        )
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A category with this name already exists.",
        )

    category.name = payload.name
    category.description = payload.description
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        if _category_name_conflict(error):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A category with this name already exists.",
            ) from error
        raise
    db.refresh(category)
    return category


@router.delete(
    "/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an unused category",
    description="A category can only be deleted if no products use it.",
    responses={
        404: {"description": "Category not found."},
        409: {"description": "Category is assigned to one or more products."},
    },
)
def delete_category(category_id: int, db: Session = Depends(get_db)) -> Response:
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Category not found."
        )

    product_exists = db.scalar(
        select(Product.id).where(Product.category_id == category_id).limit(1)
    )
    if product_exists is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Category cannot be deleted while products use it.",
        )

    db.delete(category)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
