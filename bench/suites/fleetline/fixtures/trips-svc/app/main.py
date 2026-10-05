from fastapi import FastAPI

from app.routes import router

app = FastAPI(title="trips-svc")
app.include_router(router)
