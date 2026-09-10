from fastapi import FastAPI
from app.config.database import Base, engine
from app.models import (
    user_model,
    category_model,
    product_model,
    vendor_model,
    cart_model,
    wishlist_model,
    order_model,
)
from app.routes import auth, category, product, vendor, admin, cart, wishlist

Base.metadata.create_all(bind=engine)

app = FastAPI(title="E-Commerce API")

app.include_router(auth.router)
app.include_router(category.router)
app.include_router(product.router)
app.include_router(vendor.router)
app.include_router(admin.router)
app.include_router(cart.router)
app.include_router(wishlist.router)


@app.get("/")
def root():
    return {"message": "E-Commerce API running successfully"}
