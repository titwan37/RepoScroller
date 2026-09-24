"""Conversational interrogation endpoints (JSON and Server-Sent Events)."""

import json
import asyncio
from typing import Dict, Any, Optional
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from reposcroller.agents.duplicate_agent import DuplicateResolverAgent

router = APIRouter(prefix="/chat", tags=["Interrogation Chatbot"])


class InterrogationRequest(BaseModel):
    query: str
    file_path: Optional[str] = None
    sha256_hash: Optional[str] = None
    query_text: Optional[str] = None


@router.post("/interrogate")
def interrogate_repository(req: InterrogationRequest) -> Dict[str, Any]:
    """Interrogate repository: duplicate checks, version lineage, and single-source-of-truth answers."""
    agent = DuplicateResolverAgent()
    result = agent.interrogate(
        query=req.query,
        file_path=req.file_path,
        sha256_hash=req.sha256_hash,
        query_text=req.query_text,
    )
    return result


@router.get("/stream")
async def stream_interrogation(
    query: str = Query(..., description="User interrogation prompt"),
    sha256_hash: Optional[str] = Query(None)
):
    """Server-Sent Events (SSE) streaming endpoint for conversational UI."""
    agent = DuplicateResolverAgent()

    async def event_generator():
        yield f"data: {json.dumps({'type': 'status', 'message': 'Searching SQLite WAL ledger & SimHash indexes...'})}\n\n"
        await asyncio.sleep(0.05)

        # Run resolution agent
        result = agent.interrogate(query=query, sha256_hash=sha256_hash)

        yield f"data: {json.dumps({'type': 'category', 'status_category': result['status_category']})}\n\n"
        await asyncio.sleep(0.05)

        # Stream answer chunks
        answer_text = result["answer"]
        chunk_size = 64
        for i in range(0, len(answer_text), chunk_size):
            chunk = answer_text[i:i + chunk_size]
            yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
            await asyncio.sleep(0.02)

        yield f"data: {json.dumps({'type': 'recommendation', 'recommendation': result['recommendation']})}\n\n"
        yield f"data: {json.dumps({'type': 'sources', 'sources': result['sources']})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
