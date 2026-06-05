"""Main FastAPI Application"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api import health, telemetry

# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router)
app.include_router(telemetry.router)


@app.on_event("startup")
async def startup_event():
    """Application startup event"""
    print(f"Starting {settings.app_name} v{settings.app_version}")


@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown event"""
    print(f"Shutting down {settings.app_name}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
