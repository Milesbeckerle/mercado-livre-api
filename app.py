import os
from typing import Any, Dict, List

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

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
    query: str = Query(..., min_length=1, description="Termo pesquisado"),
    limit: int = Query(10, gt=0, le=MAX_LIMIT, description="Máximo de itens (inteiro positivo)"),
) -> JSONResponse:
    """
    Contrato do desafio:
    - Sempre retornar JSON com: query, limit, items (lista) e warnings (lista).
    - Para cada item retornado, retornar reviews associadas (lista; pode ser vazia).
    - Em falha/ausência de reviews: reviews = [] e NÃO quebrar a resposta.
    - Em falha de busca de itens (403/401/429/timeout/etc): items = [] e warnings explicando.
    """
    client = MercadoLivreClient()
    warnings: List[str] = []

    # 1) Buscar itens (sem quebrar a resposta em caso de erro do Mercado Livre)
    try:
        items = await client.search_items(query=query, limit=limit)
    except MercadoLivreError as exc:
        warnings.append(f"Erro ao buscar itens no Mercado Livre ({exc.status_code}): {exc.message}")
        items = []
    except Exception as exc:
        warnings.append(f"Erro inesperado ao buscar itens no Mercado Livre: {type(exc).__name__}")
        items = []

    # 2) Para cada item, buscar reviews (sem quebrar a resposta)
    try:
        items_with_reviews, review_warnings = await client.attach_reviews(items)
        warnings.extend(review_warnings or [])
    except Exception:
        # Regra de ouro: nunca quebrar por falha de reviews
        items_with_reviews = [{**item, "reviews": []} for item in (items or [])]
        warnings.append("Falha ao buscar reviews; retornando reviews vazias.")

    payload: Dict[str, Any] = {
        "query": query,
        "limit": limit,
        "items": items_with_reviews,
        "warnings": warnings,
    }

    return JSONResponse(payload)
