import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_user
from app.dependencies.database import get_db
from app.models.order import Order, OrderStatus, OrderStatusHistory
from app.models.payment import Payment, PaymentStatus
from app.models.user import User
from app.schemas.payment import PaymentInitiate, PaymentResponse

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.post(
    "/",
    response_model=PaymentResponse,
    status_code=status.HTTP_200_OK,
    summary="Process payment for an order with Idempotency Key protection"
)
def process_payment(
    payment_in: PaymentInitiate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Mock payment processing endpoint.
    
    IDEMPOTENCY HANDLING:
    - Checks if the given `idempotency_key` was already used.
    - If found, immediately returns the previously created Payment record.
    - Prevents double charging on network retries, page refreshes, or rapid clicks.
    """
    # 1. Idempotency Check
    existing_payment = db.query(Payment).filter(
        Payment.idempotency_key == payment_in.idempotency_key
    ).first()

    if existing_payment:
        # Idempotent response: return previously processed payment directly!
        return existing_payment

    # 2. Fetch and validate order
    order = db.query(Order).filter(Order.id == payment_in.order_id).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found."
        )

    if order.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to pay for another user's order."
        )

    if order.status != OrderStatus.CREATED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Order is in '{order.status}' status and cannot be paid for."
        )

    # Check if a successful payment already exists for this order
    prior_success = db.query(Payment).filter(
        Payment.order_id == order.id,
        Payment.status == PaymentStatus.SUCCESS
    ).first()
    if prior_success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This order has already been paid for."
        )

    # 3. Simulate Payment Gateway Transaction
    if payment_in.should_succeed:
        txn_status = PaymentStatus.SUCCESS
        txn_id = f"txn_mock_{uuid.uuid4().hex[:12]}"

        # Transition order to CONFIRMED
        order.status = OrderStatus.CONFIRMED

        # Log state transition history
        history = OrderStatusHistory(
            order_id=order.id,
            old_status=OrderStatus.CREATED.value,
            new_status=OrderStatus.CONFIRMED.value,
            changed_by_user_id=current_user.id,
            notes=f"Payment verified via {payment_in.payment_method} (Txn: {txn_id})"
        )
        db.add(history)
    else:
        txn_status = PaymentStatus.FAILED
        txn_id = f"txn_fail_{uuid.uuid4().hex[:12]}"

    # 4. Save Payment record
    payment = Payment(
        order_id=order.id,
        amount=order.grand_total,
        status=txn_status,
        payment_method=payment_in.payment_method,
        transaction_id=txn_id,
        idempotency_key=payment_in.idempotency_key
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment
