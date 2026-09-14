from __future__ import annotations

import queue
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.sessions import AgentSession, InMemorySessionStore, SessionStore, build_orchestrator, sse


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)


class ChatResponse(BaseModel):
    response: str


def create_app(store: SessionStore | None = None) -> FastAPI:
    app = FastAPI(title="TravelAgent API")
    app.state.sessions = store or InMemorySessionStore()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def session(x_session_id: str = Header(alias="X-Session-ID")) -> AgentSession:
        try:
            UUID(x_session_id)
        except ValueError:
            raise HTTPException(400, "X-Session-ID must be a UUID")
        return app.state.sessions.get(x_session_id)

    @app.post("/api/chat", response_model=ChatResponse)
    def chat(body: ChatRequest, current: AgentSession = Depends(session)):
        with current.lock:
            if current.orchestrator is None:
                current.orchestrator = build_orchestrator(current)
            response = current.orchestrator.turn(body.message)
            current.refresh_artifacts()
        return {"response": response}

    @app.get("/api/events")
    def events(current: AgentSession = Depends(session)):
        subscriber = current.notifier.subscribe(replay=True)

        def stream():
            try:
                while True:
                    try:
                        event = subscriber.get(timeout=15)
                        yield sse(event)
                    except queue.Empty:
                        yield ": keep-alive\n\n"
            finally:
                current.notifier.unsubscribe(subscriber)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/artifacts")
    def artifacts(current: AgentSession = Depends(session)):
        current.refresh_artifacts()
        return [{"id": item.id, "name": item.name} for item in current.artifacts.values()]

    @app.get("/api/artifacts/{artifact_id}")
    def artifact(artifact_id: str, current: AgentSession = Depends(session)):
        current.refresh_artifacts()
        item = current.artifacts.get(artifact_id)
        if not item:
            raise HTTPException(404, "Artifact not found")
        return {"id": item.id, "name": item.name, "content": item.content}

    return app


app = create_app()
