import os
import json
import razorpay
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from sqlmodel import SQLModel, Field, create_engine, Session, select
from pydantic import BaseModel
from typing import Optional
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Load Razorpay credentials from environment variables
RAZORPAY_KEY_ID = "rzp_test_XscoZaTm58ffUp"
RAZORPAY_KEY_SECRET = "rfBusA6e4olcHLwAniWyVjYA"
RAZORPAY_WEBHOOK_SECRET = "jai1019"
if not all([RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET]):
    raise EnvironmentError(
        "Please set RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, and RAZORPAY_WEBHOOK_SECRET"
    )

# Initialize Razorpay client
client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# Initialize FastAPI app
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (index.html, etc.)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    return FileResponse("static/index.html")



# Database configuration (SQLite)
DATABASE_URL = "sqlite:///./payments.db"
engine = create_engine(DATABASE_URL, echo=True)

# Define Transaction model
class Transaction(SQLModel, table=True):
    order_id: str = Field(primary_key=True, index=True)
    payment_id: str
    status: str
    amount: int       # in paise
    currency: str
    method: str
    email: Optional[str] = None
    contact: Optional[str] = None

# Create tables
SQLModel.metadata.create_all(engine)

# Dependency to get DB session
def get_session():
    with Session(engine) as session:
        yield session

# Pydantic schemas for request/response
class OrderRequest(BaseModel):
    amount: int
    currency: Optional[str] = "INR"
    receipt: Optional[str] = None

class OrderResponse(BaseModel):
    order_id: str
    amount: int       # in paise
    currency: str
    key_id: str

# Endpoint: Create a Razorpay order
@app.post("/create_order", response_model=OrderResponse)
async def create_order(req: OrderRequest):
    amount_paise = req.amount * 100
    order_data = {
        "amount": amount_paise,
        "currency": req.currency,
        "receipt": req.receipt or f"rcpt_{int(os.times()[4])}",
        "payment_capture": 1
    }
    order = client.order.create(data=order_data)
    return OrderResponse(
        order_id=order["id"],
        amount=order["amount"],
        currency=order["currency"],
        key_id=RAZORPAY_KEY_ID
    )

# Endpoint: Handle Razorpay webhooks
@app.post("/webhook")
async def webhook(request: Request, session: Session = Depends(get_session)):
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature")
    # Verify webhook signature
    try:
        client.utility.verify_webhook_signature(
            body, signature, "jai1019"
        )
    except razorpay.errors.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    payload = json.loads(body)
    # Process payment captured event
    if payload.get("event") == "payment.captured":
        p = payload["payload"]["payment"]["entity"]
        tx = Transaction(
            order_id=p["order_id"],
            payment_id=p["id"],
            status=p["status"],
            amount=p["amount"],
            currency=p["currency"],
            method=p["method"],
            email=p.get("email"),
            contact=p.get("contact")
        )
        session.add(tx)
        session.commit()

    return JSONResponse(status_code=200, content={"status": "ok"})

# Endpoint: Retrieve transaction details
@app.get("/transactions/{order_id}", response_model=Transaction)
async def get_transaction(order_id: str, session: Session = Depends(get_session)):
    statement = select(Transaction).where(Transaction.order_id == order_id)
    tx = session.exec(statement).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return tx

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)
# To run locally:
# uvicorn main:app --reload --host 0.0.0.0 --port 8000
