import os

import uvicorn
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from auth import router as auth_router
from chats import router as chats_router
from database import init_db
from reviews import router as reviews_router

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
        ).split(",")
        if origin.strip()
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)
app.include_router(auth_router)
app.include_router(chats_router)
app.include_router(reviews_router)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Ne pas recopier les mots de passe dans les erreurs de validation Pydantic.
    return JSONResponse(
        status_code=422,
        content={"detail": "Vérifiez les champs du formulaire."},
    )


@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    return JSONResponse(
        status_code=503,
        content={"detail": "Service temporairement indisponible."},
    )


@app.get("/")
async def hello():
    return {"message": "👋"}


if __name__ == "__main__":
    init_db()

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
