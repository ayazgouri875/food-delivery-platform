from fastapi import FastAPI
from sqlalchemy import text

from app.core.config import settings
from app.database import Base, engine
from app.models import User  # Ensures models are imported before create_all
from app.routers import auth_router, users_router

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Production-grade Food Delivery Backend API (Swiggy/Zomato clone)",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Automatically create database tables for development
Base.metadata.create_all(bind=engine)

# Mount domain routers
app.include_router(auth_router)
app.include_router(users_router)


@app.get("/", tags=["General"])
def root():
    return {
        "project": settings.PROJECT_NAME,
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health"
    }


@app.get("/health", tags=["General"])
def health_check():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            return {
                "status": "healthy",
                "database": "connected"
            }
    except Exception as e:
        return {
            "status": "unhealthy",
            "database": str(e)
        }