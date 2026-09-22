"""
ASGI application for Yargı MCP Server

This module provides ASGI/HTTP access to the Yargı MCP server,
allowing it to be deployed as a web service with FastAPI wrapper.

Usage:
    uvicorn asgi_app:app --host 0.0.0.0 --port 8000
"""

import asyncio
import datetime
import os
import json
import logging
import httpx
import inspect
from fastapi import FastAPI, HTTPException, Query, Depends, Body, Request, Response
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from mcp_server_main import create_app

# Setup logging
logger = logging.getLogger(__name__)

# Configure CORS
cors_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")

# Create MCP app
mcp_server = create_app()

# Create MCP Starlette sub-application
mcp_app = mcp_server.http_app(path="/")
SERVER_START_TIME = datetime.datetime.now()


async def fetch_documents_sequential(decisions, delay=1.0):
    documents = []
    for d in decisions:
        doc = await fetch_document(d.get("document_url"))
        documents.append(doc)
        await asyncio.sleep(delay)
    return documents

# Configure JSON encoder for proper Turkish character support
class UTF8JSONResponse(JSONResponse):
    def __init__(self, content=None, status_code=200, headers=None, **kwargs):
        if headers is None:
            headers = {}
        headers["Content-Type"] = "application/json; charset=utf-8"
        super().__init__(content, status_code, headers, **kwargs)

    def render(self, content) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
        ).encode("utf-8")

custom_middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID", "X-Session-ID"],
    ),
]

# Create FastAPI wrapper application
app = FastAPI(
    title="Yargı MCP Server",
    description="MCP server for Turkish legal databases",
    version="0.1.0",
    middleware=custom_middleware,
    default_response_class=UTF8JSONResponse,
    redirect_slashes=False,
)

class ToolInfo(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]
    
async def call_mcp_tool(tool_name: str, arguments: Dict[str, Any]):
    """Call an MCP tool with given arguments using official FastMCP API"""
    try:
        result = await asyncio.wait_for(
            mcp_server.call_tool(tool_name, arguments),
            timeout=120.0,
        )

        if isinstance(result, list) and len(result) > 0:
            item = result[0]
            if hasattr(item, "text"):
                try:
                    return json.loads(item.text)
                except (json.JSONDecodeError, TypeError):
                    return item.text

        return result

    except asyncio.TimeoutError as exc:
        logger.error(f"MCP tool '{tool_name}' timed out after 120 seconds")
        raise HTTPException(status_code=504, detail="MCP tool request timed out") from exc
    except Exception as e:
        error_msg = str(e)
        if "not found" in error_msg.lower() or "unknown" in error_msg.lower():
            raise HTTPException(
                status_code=404, detail=f"Tool '{tool_name}' not found"
            )

        raise HTTPException(
            status_code=500, detail=f"Tool execution failed: {error_msg}"
        )




@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring"""
    return {
        "status": "healthy",
        "service": "Yargı MCP Server",
        "version": "0.1.0",
        "start_time": SERVER_START_TIME.isoformat(),
    }

@app.get("/debug/mcp_attrs")
async def debug_mcp_attrs():
    try:
        tools = await mcp_server.list_tools()

        candidates = []
        for tool in tools:
            # Tool nesnesinden ham veri çekme
            if hasattr(tool, "model_dump"):
                tool_dict = tool.model_dump()
            elif hasattr(tool, "dict"):
                tool_dict = tool.dict()
            elif hasattr(tool, "__dict__"):
                tool_dict = vars(tool)
            else:
                tool_dict = {"repr": str(tool)}

            candidates.append(tool_dict)

        debug_payload = {
            "count": len(candidates),
            "candidates": candidates,
            "raw_registered_tools": list(mcp_server._tools.keys())
            if hasattr(mcp_server, "_tools")
            else [],
        }

        # default=str parametresi <class 'function'> dahil JSON'a girmeyen her şeyi string yapar
        json_bytes = json.dumps(debug_payload, default=str, indent=2)
        return Response(content=json_bytes, media_type="application/json")

    except Exception as e:
        error_payload = {
            "error": str(e),
            "raw_tools_keys": list(mcp_server._tools.keys())
            if hasattr(mcp_server, "_tools")
            else [],
        }
        return Response(
            content=json.dumps(error_payload, default=str),
            media_type="application/json",
            status_code=500,
        )
@app.api_route("/mcp", methods=["GET", "POST", "HEAD", "OPTIONS"])
async def redirect_to_slash(request: Request):
    """Redirect /mcp to /mcp/ preserving HTTP method with 308"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/mcp/", status_code=308)

class YargitaySearchRequest(BaseModel):
    
    """
    Search request for Court of Cassation (Yargıtay) decisions using primary official API.
    
    The Court of Cassation is Turkey's highest court for civil and criminal matters,
    equivalent to a Supreme Court. Provides access to comprehensive supreme court precedents.
    """
    arananKelime: str = Field(
        ..., 
        description="""Keyword to search for with advanced operators:
        • Space between words = OR logic (arsa payı → "arsa" OR "payı")
        • "exact phrase" = Exact match ("arsa payı" → exact phrase)
        • word1+word2 = AND logic (arsa+payı → both words required)
        • word* = Wildcard (bozma* → bozma, bozması, bozmanın, etc.)
        • +"phrase1" +"phrase2" = Multiple required phrases
        • +"required" -"excluded" = Include and exclude
        
        Turkish Examples:
        • Simple OR: arsa payı (~523K results)
        • Exact phrase: "arsa payı" (~22K results)
        • Multiple AND: +"arsa payı" +"bozma sebebi" (~234 results)
        • Wildcard: bozma* (bozma, bozması, bozmanın, etc.)
        • Exclude: +"arsa payı" -"kira sözleşmesi"
        """,
        example='+"mülkiyet hakkı" +"iptal"'
    )
    birimYrgKurulDaire: Optional[str] = Field(
        "", 
        description="""Chamber/board selection (52 options):
        Civil Chambers: 1-23. Hukuk Dairesi
        Criminal Chambers: 1-23. Ceza Dairesi
        General Assemblies: Hukuk Genel Kurulu, Ceza Genel Kurulu
        Special Boards: Hukuk/Ceza Daireleri Başkanlar Kurulu, Büyük Genel Kurulu
        
        Use "" for ALL chambers or specify exact chamber name.
        """,
        example="1. Hukuk Dairesi"
    )
    birimYrgHukukDaire: Optional[str] = Field(
        "",
        description="""General Assembly selection (2 options):
        Hukuk Genel Kurulu (Civil General Assembly)
        Ceza Genel Kurulu (Criminal General Assembly)
        """,
        example="Hukuk Genel Kurulu"
    )
    baslangicTarihi: Optional[str] = Field(None, description="Start date (DD.MM.YYYY)", example="01.01.2020")
    bitisTarihi: Optional[str] = Field(None, description="End date (DD.MM.YYYY)", example="31.12.2024")
    pageSize: int = Field(20, description="Results per page (1-100)", ge=1, le=100, example=20)
    pageNumber: int = Field(1, description="Page number (1-indexed)", ge=1, example=1)




async def fetch_document(document_url: str) -> str:
    if not document_url:
        logger.warning("Document URL is empty or None")
        return None
    
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            response = await client.get(document_url)
            logger.info(f"Fetched document from {document_url} with status code {response.status_code}")
            return response.text
    except Exception as e:
        logger.error(f"Doküman çekilemedi: {document_url} - {e}")
        return None






@app.get("/")
async def root():
    """Root endpoint with service information"""
    public_attrs = []
    public_methods = []

    for name in dir(mcp_server):
        if name.startswith("_"):
            continue
        value = getattr(mcp_server, name)
        if callable(value):
            public_methods.append(name)
        else:
            public_attrs.append(name)

    return {
        "service": "Yargı MCP Server",
        "description": "MCP server for Turkish legal databases",
        "start_time": SERVER_START_TIME.isoformat(),
        "endpoints": {
            "mcp": "/mcp",
            "health": "/health",
            "status": "/status",
        },
        "transports": {
            "http": "/mcp"
        },
        "supported_databases": [
            "Yargıtay (Court of Cassation)",
            "Danıştay (Council of State)",
            "Emsal (Precedent)",
            "Uyuşmazlık Mahkemesi (Court of Jurisdictional Disputes)",
            "Anayasa Mahkemesi (Constitutional Court)",
            "Kamu İhale Kurulu (Public Procurement Authority)",
            "Rekabet Kurumu (Competition Authority)",
            "Sayıştay (Court of Accounts)",
            "KVKK (Personal Data Protection Authority)",
            "BDDK (Banking Regulation and Supervision Agency)",
            "BTK (Information and Communication Technologies Authority)",
            "Bedesten API (Multiple courts)",
            "Sigorta Tahkim Komisyonu (Insurance Arbitration Commission)",
        ],
        "mcp_object": str(mcp_server),
        "public_attributes": public_attrs,
        "public_methods": public_methods,
    }


# Mount MCP app at /mcp/
app.mount("/mcp/", mcp_app)

# Set the lifespan context after mounting
app.router.lifespan_context = mcp_app.lifespan

# Export for uvicorn
__all__ = ["app"]
