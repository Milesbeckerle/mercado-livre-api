# API Mercado Livre – Buscar Itens + Reviews

Projeto em **FastAPI** que consulta a API do Mercado Livre, retorna itens de busca e agrega reviews por item.

## ✅ Funcionalidades

- `GET /search?query=<termo>&limit=<max_itens>`
- `GET /health`
- Frontend simples em `/` com formulário de busca e cards
- Controle de concorrência (semaforo) para reviews
- Retry com backoff para 429/5xx
- Tratamento de falhas nas reviews sem quebrar a resposta

## 🧩 Variáveis de ambiente

| Variável | Default | Descrição |
| --- | --- | --- |
| `ML_SITE_ID` | `MLB` | Site do Mercado Livre |
| `ML_ACCESS_TOKEN` | (vazio) | Token para endpoints que exigirem autenticação |
| `MAX_LIMIT` | `50` | Limite máximo aceito no parâmetro `limit` |
| `PORT` | `8000` | Porta do servidor |

## ▶️ Executar localmente

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload
```

A aplicação estará disponível em `http://localhost:8000`.

## 🐳 Rodar com Docker

```bash
docker build -t ml-api .
docker run -p 8000:8000 -e PORT=8000 ml-api
```

## 📌 Endpoints

### `GET /health`

Resposta:

```json
{"status": "ok"}
```

### `GET /search?query=<termo>&limit=<max_itens>`

Resposta (exemplo):

```json
{
  "query": "notebook",
  "limit": 5,
  "items": [
    {
      "id": "MLB123",
      "title": "Notebook XYZ",
      "price": 2500.0,
      "image": "https://...",
      "reviews": []
    }
  ],
  "warnings": [
    "Rate limit ao buscar reviews do item MLB123."
  ]
}
```

## ⚠️ Tratamento de erros

- Para **401/403** nas reviews: retorna `reviews: []` e adiciona aviso.
- Para **404** nas reviews: retorna `reviews: []` sem aviso.
- Para **429/5xx** nas reviews: retry com backoff (até 3 tentativas). Se falhar, retorna `reviews: []` e adiciona aviso.
- Erros de rede e timeout geram avisos (se ocorrerem em reviews) ou erro 502 (se ocorrerem na busca).

## 🧠 Decisões técnicas

- `httpx.AsyncClient` com retry e backoff exponencial.
- Semáforo de concorrência (8) para não sobrecarregar o endpoint de reviews.
- Frontend em HTML simples para facilitar testes manuais.

