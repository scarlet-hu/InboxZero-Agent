import os

from app.api.auth import router as auth_router
from app.api.endpoints import router as agent_router
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Inbox Zero Agent API")

# CORS: the Next.js dev server lives at a different origin from FastAPI.
# allow_credentials=True is required so the session cookie crosses origins.
_frontend_origin = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/auth")
app.include_router(agent_router, prefix="/agent")

@app.get("/")
def root():
    return {"message": "Inbox Zero Agent API is running"}

if __name__ == "__main__":
    import uvicorn
    # Reload=True is great for development
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
