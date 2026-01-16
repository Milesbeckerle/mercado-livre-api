import os
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from httpx import HTTPError

from ml_client import MercadoLivreClient, MercadoLivreError

MAX_LIMIT = int(os.getenv("MAX_LIMIT", "50"))

app = FastAPI(title="API Mercado Livre - Search + Reviews")

templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/search")
async def search(
    query: str = Query(..., min_length=1),
    limit: int = Query(10, gt=0, le=MAX_LIMIT),
) -> JSONResponse:
    client = MercadoLivreClient()

    warnings: List[str] = []

    try:
        items = await client.search_items(query=query, limit=limit)
    except MercadoLivreError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except HTTPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    items_with_reviews, review_warnings = await client.attach_reviews(items)
    warnings.extend(review_warnings)

    payload: Dict[str, Any] = {
        "query": query,
        "limit": limit,
        "items": items_with_reviews,
    }

    if warnings:
        payload["warnings"] = warnings

    return JSONResponse(payload)
