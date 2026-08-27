import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "super-secret-key-change-me")

    # Your two FastAPI services.
    USER_SERVICE_URL = os.environ.get("USER_SERVICE_URL", "http://localhost:8000").rstrip("/")
    BOOK_SERVICE_URL = os.environ.get("BOOK_SERVICE_URL", "http://localhost:8001").rstrip("/")

    BACKEND_TIMEOUT = float(os.environ.get("BACKEND_TIMEOUT", "30"))
