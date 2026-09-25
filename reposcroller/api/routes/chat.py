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
    node: Optional[str] = None  # Optional override: 'pc1' or 'pc2'
    model: Optional[str] = None


class ChatRoutingPayload(BaseModel):
    node: str  # 'pc1' or 'pc2'
    model: Optional[str] = None


@router.get("/routing")
def get_chat_routing_info():
    """Retrieve active chat node routing, available models, and node health targets."""
    from reposcroller.ai.telemetry import workload_telemetry
    return workload_telemetry.get_chat_routing()


@router.post("/routing")
def set_chat_routing_node(payload: ChatRoutingPayload):
    """Switch active LLM chat node dynamically (PC1 CPU vs PC2 CUDA GPU)."""
    from reposcroller.ai.telemetry import workload_telemetry
    res = workload_telemetry.switch_chat_routing(node=payload.node, model=payload.model)
    return {"status": "switched", "routing": res}


@router.post("/interrogate")
def interrogate_repository(req: InterrogationRequest) -> Dict[str, Any]:
    """Interrogate repository: duplicate checks, version lineage, and single-source-of-truth answers."""
    from reposcroller.ai.telemetry import workload_telemetry
    if req.node:
        workload_telemetry.switch_chat_routing(node=req.node, model=req.model)

    agent = DuplicateResolverAgent()
    result = agent.interrogate(
        query=req.query,
        file_path=req.file_path,
        sha256_hash=req.sha256_hash,
        query_text=req.query_text,
    )
    result["active_chat_node"] = workload_telemetry.chat_active_node
    result["active_chat_model"] = workload_telemetry.get_active_chat_model()
    return result


@router.get("/stream")
async def stream_interrogation(
    query: str = Query(..., description="User interrogation prompt"),
    sha256_hash: Optional[str] = Query(None),
    node: Optional[str] = Query(None, description="Optional override: 'pc1' or 'pc2'"),
    model: Optional[str] = Query(None, description="Optional model override")
):
    """Server-Sent Events (SSE) streaming endpoint for conversational UI."""
    from reposcroller.ai.telemetry import workload_telemetry
    if node:
        workload_telemetry.switch_chat_routing(node=node, model=model)
    agent = DuplicateResolverAgent()

    async def event_generator():
        yield f"data: {json.dumps({'type': 'status', 'message': 'Consulting document ledger & knowledge index...'})}\n\n"
        await asyncio.sleep(0.04)

        # Run resolution / QA agent
        result = agent.interrogate(query=query, sha256_hash=sha256_hash)

        # Emit active document context if matched or active
        canon = result.get("canonical_document")
        if canon:
            yield f"data: {json.dumps({'type': 'active_doc', 'sha256_hash': canon['sha256_hash'], 'canonical_filename': canon['canonical_filename']})}\n\n"

        yield f"data: {json.dumps({'type': 'category', 'status_category': result['status_category']})}\n\n"
        await asyncio.sleep(0.03)

        # Stream answer chunks
        answer_text = result["answer"]
        chunk_size = 48
        for i in range(0, len(answer_text), chunk_size):
            chunk = answer_text[i:i + chunk_size]
            yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
            await asyncio.sleep(0.015)

        yield f"data: {json.dumps({'type': 'recommendation', 'recommendation': result['recommendation']})}\n\n"
        yield f"data: {json.dumps({'type': 'sources', 'sources': result['sources']})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
