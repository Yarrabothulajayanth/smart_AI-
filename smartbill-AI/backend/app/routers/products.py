from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Category, Product
from app.schemas import ProductCreate, ProductRead, ProductUpdate

router = APIRouter(prefix="/products", tags=["Products"])


def _product_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Product not found."
    )


def _category_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Category not found."
    )


def _barcode_conflict(error: IntegrityError) -> bool:
    return "products.barcode" in str(error.orig)


def _ensure_category_exists(db: Session, category_id: int) -> None:
    if db.get(Category, category_id) is None:
        raise _category_not_found()


def _ensure_barcode_available(
    db: Session, barcode: str | None, product_id: int | None = None
) -> None:
    if barcode is None:
        return

    statement = select(Product.id).where(Product.barcode == barcode)
    if product_id is not None:
        statement = statement.where(Product.id != product_id)
    if db.scalar(statement) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A product with this barcode already exists.",
        )


@router.post(
    "/",
    response_model=ProductRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a product",
    description=(
        "Create a product with pricing and GST details. The selected category "
        "must already exist. Stock is not managed by this application."
    ),
    responses={
        404: {"description": "Category not found."},
        409: {"description": "Barcode is already assigned to another product."},
    },
)
def create_product(
    payload: ProductCreate, db: Session = Depends(get_db)
) -> Product:
    _ensure_category_exists(db, payload.category_id)
    _ensure_barcode_available(db, payload.barcode)

    product = Product(**payload.model_dump())
    db.add(product)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        if _barcode_conflict(error):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A product with this barcode already exists.",
            ) from error
        raise
    db.refresh(product)
    return product


@router.get(
    "/",
    response_model=list[ProductRead],
    summary="List products",
    description=(
        "List active products. Set include_inactive=true to include "
        "deactivated products."
    ),
)
def list_products(
    include_inactive: bool = Query(
        default=False, description="Include deactivated products in the results."
    ),
    db: Session = Depends(get_db),
) -> list[Product]:
    statement = select(Product)
    if not include_inactive:
        statement = statement.where(Product.is_active.is_(True))
    statement = statement.order_by(Product.name, Product.id)
    return list(db.scalars(statement).all())


@router.get(
    "/search/{name}",
    response_model=list[ProductRead],
    summary="Search products by name",
    description="Find active products whose names contain the supplied text.",
    responses={422: {"description": "The search name cannot be blank."}},
)
def search_products_by_name(
    name: str = Path(min_length=1, max_length=150),
    db: Session = Depends(get_db),
) -> list[Product]:
    search_term = name.strip()
    if not search_term:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Search name cannot be blank.",
        )

    statement = (
        select(Product)
        .where(
            Product.is_active.is_(True),
            Product.name.ilike(f"%{search_term}%"),
        )
        .order_by(Product.name, Product.id)
    )
    return list(db.scalars(statement).all())


@router.get(
    "/barcode/{barcode}",
    response_model=ProductRead,
    summary="Find a product by barcode",
    description="Find an active product using its unique barcode.",
    responses={404: {"description": "No active product has this barcode."}},
)
def get_product_by_barcode(
    barcode: str = Path(min_length=1, max_length=128),
    db: Session = Depends(get_db),
) -> Product:
    product = db.scalar(
        select(Product).where(
            Product.barcode == barcode.strip(),
            Product.is_active.is_(True),
        )
    )
    if product is None:
        raise _product_not_found()
    return product


@router.get(
    "/{product_id}",
    response_model=ProductRead,
    summary="Get a product",
    description="Return a product by its ID, including its active status.",
    responses={404: {"description": "Product not found."}},
)
def get_product(product_id: int, db: Session = Depends(get_db)) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise _product_not_found()
    return product


@router.put(
    "/{product_id}",
    response_model=ProductRead,
    summary="Update a product",
    description=(
        "Replace the product's editable pricing, GST, and catalog details."
    ),
    responses={
        404: {"description": "Product or category not found."},
        409: {"description": "Barcode is already assigned to another product."},
    },
)
def update_product(
    product_id: int,
    payload: ProductUpdate,
    db: Session = Depends(get_db),
) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise _product_not_found()

    _ensure_category_exists(db, payload.category_id)
    _ensure_barcode_available(db, payload.barcode, product_id=product_id)

    for field, value in payload.model_dump().items():
        setattr(product, field, value)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        if _barcode_conflict(error):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A product with this barcode already exists.",
            ) from error
        raise
    db.refresh(product)
    return product


@router.delete(
    "/{product_id}",
    response_model=ProductRead,
    summary="Deactivate a product",
    description=(
        "Deactivate a product instead of deleting it, preserving invoice history."
    ),
    responses={404: {"description": "Product not found."}},
)
def deactivate_product(
    product_id: int, db: Session = Depends(get_db)
) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise _product_not_found()

    product.is_active = False
    db.commit()
    db.refresh(product)
    return product
