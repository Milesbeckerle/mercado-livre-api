import asyncio
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx

DEFAULT_TIMEOUT = 10.0
MAX_RETRIES = 3
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
REVIEWS_CONCURRENCY = 8


@dataclass
class MercadoLivreError(Exception):
    status_code: int
    message: str


class MercadoLivreClient:
    def __init__(self) -> None:
        self.site_id = os.getenv("ML_SITE_ID", "MLB")
        self.access_token = os.getenv("ML_ACCESS_TOKEN")
        self.base_url = "https://api.mercadolibre.com"
        self._semaphore = asyncio.Semaphore(REVIEWS_CONCURRENCY)

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> httpx.Response:
        attempt = 0
        backoff = 0.5

        while True:
            try:
                response = await client.request(
                    method,
                    url,
                    params=params,
                    headers=headers,
                    timeout=timeout,
                )
            except httpx.TimeoutException as exc:
                attempt += 1
                if attempt >= MAX_RETRIES:
                    raise exc
                await asyncio.sleep(backoff)
                backoff *= 2
                continue

            if response.status_code in RETRY_STATUS_CODES:
                attempt += 1
                if attempt >= MAX_RETRIES:
                    return response
                await asyncio.sleep(backoff)
                backoff *= 2
                continue

            return response

    async def search_items(self, query: str, limit: int) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/sites/{self.site_id}/search"
        async with httpx.AsyncClient() as client:
            response = await self._request(
                client,
                "GET",
                url,
                params={"q": query, "limit": limit},
            )

        if response.status_code >= 400:
            raise MercadoLivreError(
                status_code=response.status_code,
                message=f"Erro ao buscar itens: {response.text}",
            )

        data = response.json()
        items = []
        for item in data.get("results", []):
            items.append(
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "price": item.get("price"),
                    "image": item.get("thumbnail")
                    or item.get("secure_thumbnail")
                    or item.get("thumbnail_id"),
                }
            )

        return items

    async def get_item_reviews(self, item_id: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        url = f"{self.base_url}/reviews/item/{item_id}"
        headers = {}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        async with httpx.AsyncClient() as client:
            response = await self._request(client, "GET", url, headers=headers)

        if response.status_code in {401, 403}:
            return [], f"Sem permissão para reviews do item {item_id}."
        if response.status_code == 404:
            return [], None
        if response.status_code == 429:
            return [], f"Rate limit ao buscar reviews do item {item_id}."
        if response.status_code >= 400:
            return [], f"Falha ao buscar reviews do item {item_id}: {response.text}"

        data = response.json()
        reviews = data.get("reviews", [])
        if not isinstance(reviews, list):
            return [], None
        return reviews, None

    async def _fetch_reviews_with_semaphore(
        self, item: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        async with self._semaphore:
            try:
                reviews, warning = await self.get_item_reviews(item["id"])
            except httpx.HTTPError as exc:
                item_with_reviews = {**item, "reviews": []}
                return (
                    item_with_reviews,
                    f"Erro de rede ao buscar reviews do item {item['id']}: {exc}",
                )
            item_with_reviews = {**item, "reviews": reviews}
            return item_with_reviews, warning

    async def attach_reviews(
        self, items: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        tasks = [self._fetch_reviews_with_semaphore(item) for item in items]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        items_with_reviews: List[Dict[str, Any]] = []
        warnings: List[str] = []
        for item, warning in results:
            items_with_reviews.append(item)
            if warning:
                warnings.append(warning)

        return items_with_reviews, warnings
