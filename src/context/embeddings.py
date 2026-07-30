# src/context/embeddings.py
from typing import List, Dict, Any, Optional, Union
import logging
import asyncio
from datetime import datetime
import numpy as np
from openai import OpenAI, RateLimitError, APITimeoutError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from src.config.settings import settings
from src.observability.tracing import tracer, trace_span

logger = logging.getLogger(__name__)

class EmbeddingProvider:
    def __init__(self):
        self.provider = settings.EMBEDDING_PROVIDER
        self.model = settings.EMBEDDING_MODEL
        self.dimension = settings.EMBEDDING_DIMENSION
        self.batch_size = settings.EMBEDDING_BATCH_SIZE
        self._cache = {}
        self._cache_enabled = settings.EMBEDDING_CACHE_ENABLED
        self._cache_size = settings.EMBEDDING_CACHE_SIZE
        self.client = None

        if self.provider == "openai":
            self.client = OpenAI(
                api_key=settings.OPENAI_API_KEY.get_secret_value() if settings.OPENAI_API_KEY else None
            )
        elif self.provider == "cohere":
            import cohere
            self.cohere_client = cohere.Client(settings.COHERE_API_KEY.get_secret_value() if settings.COHERE_API_KEY else None)
        elif self.provider == "huggingface":
            from sentence_transformers import SentenceTransformer
            self.model_instance = SentenceTransformer(settings.HUGGINGFACE_MODEL)
    
    @trace_span("embeddings.generate")
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((RateLimitError, APITimeoutError))
    )
    async def generate(self, text: Union[str, List[str]]) -> Union[List[float], List[List[float]]]:
        is_single = isinstance(text, str)
        texts = [text] if is_single else text
        
        if self._cache_enabled:
            cached_embeddings = self._get_from_cache(texts)
            if all(cached_embeddings):
                return cached_embeddings[0] if is_single else cached_embeddings
        
        all_embeddings = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            embeddings = await self._generate_batch(batch)
            all_embeddings.extend(embeddings)
        
        if self._cache_enabled:
            self._add_to_cache(texts, all_embeddings)
        
        return all_embeddings[0] if is_single else all_embeddings
    
    async def _generate_batch(self, texts: List[str]) -> List[List[float]]:
        try:
            if self.provider == "openai":
                return await self._generate_openai(texts)
            elif self.provider == "cohere":
                return await self._generate_cohere(texts)
            elif self.provider == "huggingface":
                return await self._generate_huggingface(texts)
            else:
                raise ValueError(f"Unsupported embedding provider: {self.provider}")
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            raise
    
    async def _generate_openai(self, texts: List[str]) -> List[List[float]]:
        try:
            response = await asyncio.to_thread(
                self.client.embeddings.create,
                model=self.model,
                input=texts
            )
            embeddings = [data.embedding for data in response.data]

            if embeddings and len(embeddings[0]) != self.dimension:
                logger.warning(f"Embedding dimension mismatch: expected {self.dimension}, got {len(embeddings[0])}")

            return embeddings

        except Exception as e:
            logger.error(f"OpenAI embedding failed: {e}")
            raise
    
    async def _generate_cohere(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using Cohere."""
        try:
            response = await asyncio.to_thread(
                self.cohere_client.embed,
                texts=texts,
                model=self.model
            )
            
            embeddings = response.embeddings
            
            if embeddings and len(embeddings[0]) != self.dimension:
                logger.warning(f"Embedding dimension mismatch: expected {self.dimension}, got {len(embeddings[0])}")
            
            return embeddings
            
        except Exception as e:
            logger.error(f"Cohere embedding failed: {e}")
            raise
    
    async def _generate_huggingface(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using HuggingFace models."""
        try:
            embeddings = await asyncio.to_thread(
                self.model_instance.encode,
                texts,
                convert_to_tensor=False
            )
            
            # Convert to list if numpy array
            if isinstance(embeddings, np.ndarray):
                embeddings = embeddings.tolist()
            
            if embeddings and len(embeddings[0]) != self.dimension:
                logger.warning(f"Embedding dimension mismatch: expected {self.dimension}, got {len(embeddings[0])}")
            
            return embeddings
            
        except Exception as e:
            logger.error(f"HuggingFace embedding failed: {e}")
            raise
    
    def _get_from_cache(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Get embeddings from cache."""
        results = []
        for text in texts:
            key = self._get_cache_key(text)
            results.append(self._cache.get(key))
        return results
    
    def _add_to_cache(self, texts: List[str], embeddings: List[List[float]]):
        """Add embeddings to cache."""
        for text, embedding in zip(texts, embeddings):
            key = self._get_cache_key(text)
            self._cache[key] = embedding
            
            # Limit cache size
            if len(self._cache) > self._cache_size:
                # Remove oldest entries (simple FIFO)
                keys_to_remove = list(self._cache.keys())[:len(self._cache) - self._cache_size]
                for k in keys_to_remove:
                    del self._cache[k]
    
    def _get_cache_key(self, text: str) -> str:
        """Generate cache key for text."""
        import hashlib
        return hashlib.md5(text.encode('utf-8')).hexdigest()
    
    async def generate_batch(self, texts: List[str], batch_size: Optional[int] = None) -> List[List[float]]:
        """Generate embeddings for multiple texts with progress tracking."""
        if not texts:
            return []
        
        batch_size = batch_size or self.batch_size
        all_embeddings = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            embeddings = await self.generate(batch)
            if isinstance(embeddings, list) and embeddings and isinstance(embeddings[0], list):
                all_embeddings.extend(embeddings)
            else:
                all_embeddings.append(embeddings)
            
            logger.debug(f"Processed batch {i//batch_size + 1}/{len(texts)//batch_size + 1}")
        
        return all_embeddings
    
    async def generate_query_embedding(self, query: str) -> List[float]:
        """Generate embedding for a search query."""
        embedding = await self.generate(query)
        return embedding
    
    async def generate_document_embedding(self, document: Dict[str, Any]) -> List[float]:
        """Generate embedding for a document."""
        text = self._prepare_document_text(document)
        embedding = await self.generate(text)
        return embedding
    
    def _prepare_document_text(self, document: Dict[str, Any]) -> str:
        """Prepare document text for embedding."""
        parts = []
        
        # Include title if available
        if document.get('title'):
            parts.append(document['title'])
        
        # Include content if available
        if document.get('content'):
            parts.append(document['content'])
        
        # Include tags if available
        if document.get('tags'):
            parts.append(' '.join(document['tags']))
        
        # Include service name if available
        if document.get('service'):
            parts.append(document['service'])
        
        return ' '.join(parts)

class EmbeddingManager:
    """Manager for embedding operations with monitoring and optimization."""
    
    def __init__(self):
        self.provider = EmbeddingProvider()
        self.embedding_stats = {
            'total_requests': 0,
            'total_texts': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'errors': 0
        }
    
    @trace_span("embeddings.manager.generate")
    async def generate(self, text: Union[str, List[str]]) -> Union[List[float], List[List[float]]]:
        """Generate embeddings with monitoring."""
        start_time = datetime.utcnow()
        
        try:
            # Track stats
            self.embedding_stats['total_requests'] += 1
            if isinstance(text, list):
                self.embedding_stats['total_texts'] += len(text)
            else:
                self.embedding_stats['total_texts'] += 1
            
            # Generate embedding
            result = await self.provider.generate(text)
            
            # Update stats
            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.debug(f"Embedding generated in {duration:.3f}s")
            
            return result
            
        except Exception as e:
            self.embedding_stats['errors'] += 1
            logger.error(f"Embedding generation failed: {e}")
            raise
    
    def get_stats(self) -> Dict[str, Any]:
        """Get embedding statistics."""
        total_requests = self.embedding_stats['total_requests']
        cache_hits = self.embedding_stats['cache_hits']
        cache_misses = self.embedding_stats['cache_misses']
        
        return {
            'total_requests': total_requests,
            'total_texts': self.embedding_stats['total_texts'],
            'cache_hit_rate': cache_hits / max(1, cache_hits + cache_misses) * 100,
            'cache_hits': cache_hits,
            'cache_misses': cache_misses,
            'errors': self.embedding_stats['errors'],
            'error_rate': self.embedding_stats['errors'] / max(1, total_requests) * 100
        }
    
    async def clear_cache(self):
        """Clear the embedding cache."""
        self.provider._cache.clear()
        logger.info("Embedding cache cleared")