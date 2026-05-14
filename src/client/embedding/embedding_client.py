import logging
import os
import ssl
from typing import List, Tuple, Optional

import httpx
import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """
    Client for generating embeddings via LiteLLM/Azure OpenAI.

    Uses the OpenAI-compatible /v1/embeddings endpoint.
    """

    def __init__(
        self,
        endpoint: str,
        model: str = "text-embedding-3-small",
        api_key: Optional[str] = None,
        ssl_cert_path: Optional[str] = None,
        timeout: float = 30.0
    ):
        """
        Initialize embedding client.

        Args:
            endpoint: LiteLLM/OpenAI compatible endpoint (e.g., https://litellm.example.com)
            model: Embedding model name (default: text-embedding-3-small)
            api_key: API key for authentication (LiteLLM master key or OpenAI key)
            ssl_cert_path: Path to CA certificate for SSL verification
            timeout: Request timeout in seconds
        """
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._api_key = api_key or os.getenv("LITELLM_API_KEY")
        self._ssl_cert_path = ssl_cert_path
        self._timeout = timeout
        self._cache: dict[str, np.ndarray] = {}
        self._http: Optional[httpx.AsyncClient] = None

        logger.info(f"[EMBEDDING] Initialized client for {self._endpoint}, model={self._model}")

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client (lazy initialization)."""
        if self._http is None:
            # Configure SSL verification
            verify: bool | ssl.SSLContext = True
            if self._ssl_cert_path:
                ssl_context = ssl.create_default_context()
                ssl_context.load_verify_locations(self._ssl_cert_path)
                verify = ssl_context

            headers = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"

            self._http = httpx.AsyncClient(
                base_url=self._endpoint,
                headers=headers,
                verify=verify,
                timeout=self._timeout
            )
        return self._http

    async def get_embedding(self, text: str, use_cache: bool = True) -> np.ndarray:
        """
        Get embedding for single text.

        Args:
            text: Text to embed
            use_cache: Whether to use cached embeddings (default: True)

        Returns:
            Normalized embedding vector as numpy array
        """
        if use_cache and text in self._cache:
            return self._cache[text]

        embeddings = await self.get_embeddings([text])
        if use_cache:
            self._cache[text] = embeddings[0]
        return embeddings[0]

    async def get_embeddings(self, texts: List[str]) -> List[np.ndarray]:
        """
        Get embeddings for multiple texts (batched API call).

        Args:
            texts: List of texts to embed

        Returns:
            List of normalized embedding vectors
        """
        if not texts:
            return []

        client = self._get_client()

        try:
            response = await client.post(
                "/v1/embeddings",
                json={
                    "model": self._model,
                    "input": texts
                }
            )
            response.raise_for_status()

            data = response.json()
            embeddings = []

            # Sort by index to maintain order (API may return out of order)
            sorted_data = sorted(data["data"], key=lambda x: x["index"])
            for item in sorted_data:
                emb = np.array(item["embedding"], dtype=np.float32)
                # Normalize for cosine similarity (dot product = cosine for normalized vectors)
                norm = np.linalg.norm(emb)
                if norm > 0:
                    emb = emb / norm
                embeddings.append(emb)

            logger.debug(
                f"[EMBEDDING] Generated {len(embeddings)} embeddings, "
                f"dim={len(embeddings[0]) if embeddings else 0}"
            )
            return embeddings

        except httpx.HTTPStatusError as e:
            logger.error(f"[EMBEDDING] API error: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"[EMBEDDING] Failed to get embeddings: {e}")
            raise

    async def find_most_similar(
        self,
        query: str,
        candidates: List[str],
        top_k: int = 5
    ) -> List[Tuple[int, float]]:
        """
        Find top-k most similar candidates to query.

        Args:
            query: Query text to compare against
            candidates: List of candidate texts
            top_k: Number of top results to return

        Returns:
            List of (index, similarity_score) tuples, sorted by similarity descending
        """
        if not candidates:
            return []

        # Batch all texts for efficiency (single API call)
        all_texts = [query] + candidates
        embeddings = await self.get_embeddings(all_texts)

        query_emb = embeddings[0]
        candidate_embs = np.array(embeddings[1:])

        # Cosine similarity (embeddings are normalized, so dot product = cosine)
        similarities = np.dot(candidate_embs, query_emb)

        # Get top-k indices (descending order)
        top_indices = np.argsort(similarities)[::-1][:top_k]

        results = [(int(idx), float(similarities[idx])) for idx in top_indices]

        logger.debug(
            f"[EMBEDDING] Similarity search: query vs {len(candidates)} candidates, "
            f"top match similarity={results[0][1]:.3f}" if results else ""
        )

        return results

    def clear_cache(self):
        """Clear the embedding cache."""
        self._cache.clear()
        logger.debug("[EMBEDDING] Cache cleared")

    async def close(self):
        """Close HTTP client and release resources."""
        if self._http:
            await self._http.aclose()
            self._http = None
            logger.debug("[EMBEDDING] Client closed")
