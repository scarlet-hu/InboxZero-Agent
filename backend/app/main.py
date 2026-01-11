from fastapi import FastAPI
from app.api.endpoints import router as agent_router

app = FastAPI(title="Inbox Zero Agent API")

# Include the router we defined in endpoints.py
app.include_router(agent_router, prefix="/agent")

@app.get("/")
def root():
    return {"message": "Inbox Zero Agent API is running"}

if __name__ == "__main__":
    import uvicorn
    # Reload=True is great for development
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)