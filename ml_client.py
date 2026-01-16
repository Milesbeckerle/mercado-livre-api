import asyncio
import os
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx

DEFAULT_TIMEOUT = 12.0
MAX_RETRIES = 3
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
REVIEWS_CONCURRENCY = 8


@dataclass
class MercadoLivreError(Exception):
    status_code: int
    message: str


def _backoff_seconds(attempt: int) -> float:
    base = min(8.0, 0.6 * (2 ** attempt))
    return base + random.uniform(0, 0.35)


class MercadoLivreClient:
    def __init__(self) -> None:
        self.site_id = os.getenv("ML_SITE_ID", "MLB")
        self.access_token = os.getenv("ML_ACCESS_TOKEN")
        self.proxy_url = os.getenv("PROXY_URL")  # opcional (resolve bloqueio de IP no Render)
        self.base_url = "https://api.mercadolibre.com"
        self.semaphore = asyncio.Semaphore(REVIEWS_CONCURRENCY)

    def _default_headers(self) -> Dict[str, str]:
        # Headers estilo navegador (às vezes evita 403 em cloud)
        headers: Dict[str, str] = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Connection": "keep-alive",
            "Referer": "https://www.mercadolivre.com.br/",
        }
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def _client(self) -> httpx.AsyncClient:
        # Nota: dependendo da versão do httpx, pode ser "proxy=" ou "proxies="
        # Se der erro no deploy dizendo proxy inválido, me mande o log que eu ajusto em 10s.
        kwargs: Dict[str, Any] = {
            "timeout": httpx.Timeout(DEFAULT_TIMEOUT),
            "follow_redirects": True,
            "headers": self._default_headers(),
        }
        if self.proxy_url:
            kwargs["proxy"] = self.proxy_url
        return httpx.AsyncClient(**kwargs)

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> httpx.Response:
        merged_headers = self._default_headers()
        if headers:
            merged_headers.update(headers)

        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = await client.request(
                    method=method,
                    url=url,
                    params=params,
                    headers=merged_headers,
                    timeout=timeout,
                )

                if resp.status_code in RETRY_STATUS_CODES:
                    if attempt == MAX_RETRIES:
                        return resp
                    await asyncio.sleep(_backoff_seconds(attempt))
                    continue

                return resp

            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == MAX_RETRIES:
                    raise exc
                await asyncio.sleep(_backoff_seconds(attempt))

        return await client.request(method=method, url=url, params=params, headers=merged_headers, timeout=timeout)

    async def search_items(self, query: str, limit: int) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/sites/{self.site_id}/search"

        async with self._client() as client:
            resp = await self._request(client, "GET", url, params={"q": query, "limit": limit})

        if resp.status_code == 403:
            # mensagem clara (o seu erro atual)
            raise MercadoLivreError(
                status_code=403,
                message=(
                    "403 forbidden do Mercado Livre. Isso costuma ser bloqueio de IP/datacenter "
                    "(Render). Solução: configurar PROXY_URL no Render (proxy HTTP/HTTPS) "
                    "ou rodar em outro host/IP."
                ),
            )

        if resp.status_code != 200:
            raise MercadoLivreError(
                status_code=resp.status_code,
                message=f"Erro ao buscar itens: {resp.text}",
            )

        data = resp.json() or {}
        results = data.get("results", []) or []

        items: List[Dict[str, Any]] = []
        for item in results[:limit]:
            image_url = item.get("secure_thumbnail") or item.get("thumbnail")  # sempre URL
            items.append(
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "price": item.get("price"),
                    "image": image_url,
                }
            )

        return items

    async def get_item_reviews(self, item_id: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """
        Sempre retorna (lista_reviews, warning). Nunca quebra a API final.
        """
        url = f"{self.base_url}/reviews/item/{item_id}"

        async with self._client() as client:
            try:
                resp = await self._request(client, "GET", url)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                return [], f"network_error ao buscar reviews ({item_id}): {exc}"

        if resp.status_code in (401, 403):
            return [], f"forbidden_or_unauthorized ({resp.status_code}) ao buscar reviews ({item_id})"
        if resp.status_code == 404:
            return [], None
        if resp.status_code == 429:
            return [], f"rate_limited (429) ao buscar reviews ({item_id})"
        if resp.status_code != 200:
            return [], f"erro ({resp.status_code}) ao buscar reviews ({item_id})"

        data = resp.json() or {}
        reviews = data.get("reviews", []) or []
        if isinstance(reviews, list):
            return reviews, None
        return [], None

    async def _fetch_reviews_with_semaphore(
        self, item: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        async with self.semaphore:
            item_id = item.get("id")
            if not item_id:
                return {**item, "reviews": []}, None

            reviews, warning = await self.get_item_reviews(item_id)
            return {**item, "reviews": reviews or []}, warning

    async def attach_reviews(
        self, items: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        tasks = [self._fetch_reviews_with_semaphore(item) for item in items]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        items_with_reviews: List[Dict[str, Any]] = []
        warnings: List[str] = []

        for item_with_reviews, warning in results:
            items_with_reviews.append(item_with_reviews)
            if warning:
                warnings.append(warning)

        return items_with_reviews, warnings
