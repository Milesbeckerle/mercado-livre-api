import os
from typing import Any, Dict, List

from fastapi import FastAPI, Query, Request
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


def _normalize_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Garante o contrato mínimo por item:
      - title
      - price
      - image (URL ou None)
      - permalink
      - reviews (lista; pode ser vazia)
    """
    normalized: List[Dict[str, Any]] = []

    for it in items or []:
        title = it.get("title") or it.get("name") or ""
        price = it.get("price")
        permalink = it.get("permalink") or it.get("url") or None

        # Garante que image seja URL (não thumbnail_id)
        image = it.get("secure_thumbnail") or it.get("thumbnail") or it.get("image")
        if image and isinstance(image, str) and image.startswith(("http://", "https://")):
            image_url = image
        else:
            image_url = None

        reviews = it.get("reviews")
        if not isinstance(reviews, list):
            reviews = []

        normalized.append(
            {
                "id": it.get("id"),
                "title": title,
                "price": price,
                "image": image_url,
                "permalink": permalink,
                "reviews": reviews,
            }
        )

    return normalized


@app.get("/search")
async def search(
    query: str = Query(..., min_length=1, description="Termo pesquisado"),
    limit: int = Query(10, gt=0, le=MAX_LIMIT, description="Máximo de itens retornados"),
) -> JSONResponse:
    client = MercadoLivreClient()
    warnings: List[str] = []

    # Payload base (sempre devolvido, mesmo com falhas externas)
    payload: Dict[str, Any] = {
        "query": query,
        "limit": limit,
        "count": 0,
        "items": [],
        "warnings": [],
    }

    try:
        # 1) Buscar itens
        items = await client.search_items(query=query, limit=limit)

        # 2) Para cada item, buscar reviews (quando disponíveis)
        items_with_reviews, review_warnings = await client.attach_reviews(items)

        # Normaliza contrato final
        normalized = _normalize_items(items_with_reviews)

        payload["items"] = normalized
        payload["count"] = len(normalized)

        if review_warnings:
            warnings.extend(review_warnings)

    except MercadoLivreError as exc:
        # Importante: não quebrar o contrato nem retornar 4xx/5xx
        warnings.append(
            f"Erro ao buscar itens no Mercado Livre ({exc.status_code}): {exc.message}"
        )
    except HTTPError as exc:
        warnings.append(f"Erro de rede ao chamar Mercado Livre: {str(exc)}")
    except Exception as exc:
        warnings.append(f"Erro inesperado no servidor: {str(exc)}")

    if warnings:
        payload["warnings"] = warnings

    return JSONResponse(payload)

