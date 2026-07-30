# src/context/vector_rag.py
from typing import List, Dict, Any, Optional
import logging
import asyncio
from datetime import datetime
import json
from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import PointStruct
from openai import OpenAI
from src.config.settings import settings
from src.models.schemas import PipelineAlert

logger = logging.getLogger(__name__)

class VectorRAG:
    def __init__(self):
        self.client = AsyncQdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT
        )
        self.collection_name = settings.QDRANT_COLLECTION
        self.vector_size = settings.QDRANT_VECTOR_SIZE
        self.embedding_model = "text-embedding-ada-002"
        self._collection_initialized = False
        self.openai_client = OpenAI(
            api_key=settings.OPENAI_API_KEY.get_secret_value() if settings.OPENAI_API_KEY else None
        )

    async def _ensure_collection(self):
        if self._collection_initialized:
            return
        collections = await self.client.get_collections()
        if not any(c.name == self.collection_name for c in collections.collections):
            await self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config={
                    "size": self.vector_size,
                    "distance": "Cosine"
                }
            )
            logger.info(f"Created collection: {self.collection_name}")
        self._collection_initialized = True

    async def _get_embedding(self, text: str) -> List[float]:
        response = await asyncio.to_thread(
            self.openai_client.embeddings.create,
            model=self.embedding_model,
            input=text
        )
        return response.data[0].embedding

    async def index_runbook(self, runbook: Dict[str, Any]) -> str:
        await self._ensure_collection()
        try:
            text = f"{runbook.get('title', '')} {runbook.get('content', '')}"
            embedding = await self._get_embedding(text)

            point = PointStruct(
                id=runbook.get('id', str(datetime.utcnow().timestamp())),
                vector=embedding,
                payload={
                    'title': runbook.get('title', ''),
                    'content': runbook.get('content', ''),
                    'service': runbook.get('service', ''),
                    'created_at': runbook.get('created_at', datetime.utcnow().isoformat()),
                    'tags': runbook.get('tags', []),
                    'error_patterns': runbook.get('error_patterns', []),
                    'resolution': runbook.get('resolution', ''),
                    'severity': runbook.get('severity', '')
                }
            )

            await self.client.upsert(
                collection_name=self.collection_name,
                points=[point]
            )

            logger.info(f"Indexed runbook: {runbook.get('id')}")
            return point.id

        except Exception as e:
            logger.error(f"Failed to index runbook: {e}")
            raise

    async def search_similar(self, alert: PipelineAlert, limit: int = 5) -> List[Dict[str, Any]]:
        await self._ensure_collection()
        try:
            search_text = f"{alert.error_message} {alert.service_name}"
            if alert.stack_trace:
                search_text += f" {alert.stack_trace[:1000]}"

            embedding = await self._get_embedding(search_text)

            search_result = await self.client.search(
                collection_name=self.collection_name,
                query_vector=embedding,
                limit=limit,
                with_payload=True
            )

            results = []
            for point in search_result:
                result = {
                    'id': point.id,
                    'score': point.score,
                    **point.payload
                }
                results.append(result)

            logger.info(f"Found {len(results)} similar documents for alert {alert.alert_id}")
            return results

        except Exception as e:
            logger.error(f"Failed to search similar documents: {e}")
            raise

    async def get_runbook_by_id(self, runbook_id: str) -> Optional[Dict[str, Any]]:
        await self._ensure_collection()
        try:
            points = await self.client.retrieve(
                collection_name=self.collection_name,
                ids=[runbook_id],
                with_payload=True
            )

            if points:
                return {'id': points[0].id, **points[0].payload}
            return None

        except Exception as e:
            logger.error(f"Failed to retrieve runbook {runbook_id}: {e}")
            return None

    async def delete_runbook(self, runbook_id: str) -> bool:
        await self._ensure_collection()
        try:
            await self.client.delete(
                collection_name=self.collection_name,
                points_selector=[runbook_id]
            )
            logger.info(f"Deleted runbook: {runbook_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete runbook {runbook_id}: {e}")
            return False

    async def close(self):
        await self.client.close()