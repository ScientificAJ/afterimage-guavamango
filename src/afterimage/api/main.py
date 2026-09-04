from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import router

app = FastAPI(
    title="AFTERIMAGE",
    version="0.1.0",
    description="Evidence-gated autonomous Alpaca options agent",
)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(127\.0\.0\.1|localhost):\d+$",
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Last-Event-ID"],
)
app.include_router(router)
