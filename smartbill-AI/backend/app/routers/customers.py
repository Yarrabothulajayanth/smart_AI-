from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.database import get_db
from app.models import Customer, Invoice
from app.schemas import CustomerCreate, CustomerInvoiceRead, CustomerRead, CustomerUpdate, InvoiceRead

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.post(
    "/",
    response_model=CustomerRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a customer",
    description="Add a customer record. Customers remain optional for walk-in billing.",
)
def create_customer(
    payload: CustomerCreate, db: Session = Depends(get_db)
) -> Customer:
    customer = Customer(**payload.model_dump())
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@router.get(
    "/",
    response_model=list[CustomerRead],
    summary="Search and list customers",
    description="List customers or search by name, email, or phone.",
)
def list_customers(
    search: str | None = Query(default=None, max_length=150),
    limit: int = Query(default=100, ge=1, le=250),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[Customer]:
    statement = select(Customer)
    search_term = search.strip() if search else ""
    if search_term:
        pattern = f"%{search_term}%"
        statement = statement.where(
            Customer.name.ilike(pattern)
            | Customer.email.ilike(pattern)
            | Customer.phone.ilike(pattern)
        )
    statement = (
        statement.order_by(Customer.name, Customer.id)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(statement).all())


@router.get(
    "/{customer_id}/invoices",
    response_model=list[InvoiceRead],
    summary="List a customer's invoices",
    description="Return a customer's previous invoices and payment details.",
    responses={404: {"description": "Customer not found."}},
)
def list_customer_invoices(
    customer_id: int,
    db: Session = Depends(get_db),
) -> list[Invoice]:
    if db.get(Customer, customer_id) is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    statement = (
        select(Invoice)
        .where(Invoice.customer_id == customer_id)
        .options(
            joinedload(Invoice.customer),
            selectinload(Invoice.items),
            selectinload(Invoice.payments),
        )
        .order_by(Invoice.created_at.desc(), Invoice.id.desc())
    )
    return list(db.scalars(statement).all())


@router.get(
    "/{customer_id}",
    response_model=CustomerRead,
    summary="Get customer details",
    description="Retrieve one customer's contact details.",
    responses={404: {"description": "Customer not found."}},
)
def get_customer(
    customer_id: int, db: Session = Depends(get_db)
) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    return customer


@router.put(
    "/{customer_id}",
    response_model=CustomerRead,
    summary="Update a customer",
    description="Replace a customer's contact details.",
    responses={404: {"description": "Customer not found."}},
)
def update_customer(
    customer_id: int,
    payload: CustomerUpdate,
    db: Session = Depends(get_db),
) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    for field, value in payload.model_dump().items():
        setattr(customer, field, value)
    db.commit()
    db.refresh(customer)
    return customer
