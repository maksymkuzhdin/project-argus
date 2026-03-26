"""
Project Argus — FastAPI application entry point.
"""

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.declarations import router as declarations_router
from app.api.persons import router as persons_router

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Project Argus",
    description="Ukraine declarations analysis API",
    version="0.1.0",
)

app.include_router(declarations_router)
app.include_router(persons_router)

# ---------------------------------------------------------------------------
# CORS — allow the Next.js dev server
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://frontend:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": "http_error",
                "message": str(exc.detail),
                "path": str(request.url.path),
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "Invalid request parameters.",
                "path": str(request.url.path),
                "details": exc.errors(),
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled API error at %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "Internal server error.",
                "path": str(request.url.path),
            }
        },
    )


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health")
async def health_check():
    return {"status": "ok"}
