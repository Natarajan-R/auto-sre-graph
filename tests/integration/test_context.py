# tests/integration/test_context.py
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from src.context.vector_rag import VectorRAG
from src.context.graph_rag import GraphRAG
from src.context.embeddings import EmbeddingProvider, EmbeddingManager
from tests.fixtures.sample_alerts import SampleAlerts
from tests.fixtures.mock_data import MockData, MockClients

class TestVectorRAG:
    """Integration tests for VectorRAG."""
    
    @pytest.fixture
    def vector_rag(self):
        """Create a VectorRAG instance for testing."""
        with patch("src.context.vector_rag.AsyncQdrantClient") as mock_qdrant, \
             patch("src.context.vector_rag.OpenAI") as mock_openai:
            mock_client = MockClients.get_mock_qdrant_client()
            mock_qdrant.return_value = mock_client
            mock_openai.return_value = MagicMock()
            rag = VectorRAG()
            rag._collection_initialized = True
            return rag
    
    @pytest.mark.asyncio
    async def test_search_similar(self, vector_rag):
        """Test searching for similar documents."""
        alert = SampleAlerts.get_basic_alert()
        results = await vector_rag.search_similar(alert)
        
        assert results is not None
        assert len(results) > 0
        assert "title" in results[0]
        assert "content" in results[0]
    
    @pytest.mark.asyncio
    async def test_index_runbook(self, vector_rag):
        """Test indexing a runbook."""
        runbook = {
            "id": "RUN-001",
            "title": "Test Runbook",
            "content": "Test content",
            "service": "auth-service",
            "tags": ["test"],
            "error_patterns": ["error"],
            "resolution": "Fixed",
            "severity": "HIGH"
        }
        
        doc_id = await vector_rag.index_runbook(runbook)
        assert doc_id is not None
    
    @pytest.mark.asyncio
    async def test_get_runbook_by_id(self, vector_rag):
        """Test retrieving a runbook by ID."""
        runbook_id = "RUN-001"
        result = await vector_rag.get_runbook_by_id(runbook_id)
        assert result is not None
        assert "title" in result
    
    @pytest.mark.asyncio
    async def test_delete_runbook(self, vector_rag):
        """Test deleting a runbook."""
        runbook_id = "RUN-001"
        result = await vector_rag.delete_runbook(runbook_id)
        assert result is True

class TestGraphRAG:
    """Integration tests for GraphRAG."""
    
    @pytest.fixture
    def graph_rag(self):
        """Create a GraphRAG instance for testing."""
        with patch("src.context.graph_rag.AsyncGraphDatabase.driver") as mock_driver:
            mock_client = MockClients.get_mock_neo4j_client()
            mock_driver.return_value = mock_client
            return GraphRAG()
    
    @pytest.mark.asyncio
    async def test_get_service_topology(self, graph_rag):
        """Test getting service topology."""
        topology = await graph_rag.get_service_topology("auth-service")
        
        assert topology is not None
        assert topology["service"] == "auth-service"
        assert "upstream" in topology
        assert "downstream" in topology
    
    @pytest.mark.asyncio
    async def test_get_impacted_services(self, graph_rag):
        """Test getting impacted services."""
        impacted = await graph_rag.get_impacted_services("auth-service")
        assert impacted is not None
        assert len(impacted) > 0
    
    @pytest.mark.asyncio
    async def test_add_service(self, graph_rag):
        """Test adding a service."""
        result = await graph_rag.add_service(
            "test-service",
            {"version": "v1.0.0", "team": "test-team"}
        )
        assert result is True
    
    @pytest.mark.asyncio
    async def test_add_dependency(self, graph_rag):
        """Test adding a dependency."""
        result = await graph_rag.add_dependency(
            "auth-service",
            "user-service"
        )
        assert result is True

class TestEmbeddingProvider:
    """Integration tests for EmbeddingProvider."""
    
    @pytest.fixture
    def embedding_provider(self):
        """Create an EmbeddingProvider instance for testing."""
        with patch("src.context.embeddings.settings") as mock_settings, \
             patch("src.context.embeddings.OpenAI") as mock_openai:
            mock_settings.EMBEDDING_PROVIDER = "openai"
            mock_settings.EMBEDDING_MODEL = "text-embedding-ada-002"
            mock_settings.EMBEDDING_DIMENSION = 1536
            mock_settings.EMBEDDING_BATCH_SIZE = 20
            mock_settings.EMBEDDING_CACHE_ENABLED = True
            mock_settings.EMBEDDING_CACHE_SIZE = 1000
            mock_settings.OPENAI_API_KEY = None

            mock_openai.return_value = MagicMock()

            provider = EmbeddingProvider()
            provider.client = MagicMock()
            provider.client.embeddings.create.side_effect = lambda model, input: MagicMock(
                data=[MagicMock(embedding=[0.1] * 1536) for _ in (input if isinstance(input, list) else [input])]
            )
            return provider
    
    @pytest.mark.asyncio
    async def test_generate_single(self, embedding_provider):
        """Test generating embedding for single text."""
        embedding = await embedding_provider.generate("Test text")
        assert embedding is not None
        assert len(embedding) == 1536
    
    @pytest.mark.asyncio
    async def test_generate_batch(self, embedding_provider):
        """Test generating embeddings for multiple texts."""
        texts = ["Text 1", "Text 2", "Text 3"]
        embeddings = await embedding_provider.generate_batch(texts)
        assert embeddings is not None
        assert len(embeddings) == 3
        assert all(len(emb) == 1536 for emb in embeddings)
    
    @pytest.mark.asyncio
    async def test_generate_query_embedding(self, embedding_provider):
        """Test generating query embedding."""
        embedding = await embedding_provider.generate_query_embedding("Test query")
        assert embedding is not None
        assert len(embedding) == 1536
    
    @pytest.mark.asyncio
    async def test_generate_document_embedding(self, embedding_provider):
        """Test generating document embedding."""
        document = {
            "title": "Test Document",
            "content": "Test content",
            "tags": ["tag1", "tag2"],
            "service": "test-service"
        }
        embedding = await embedding_provider.generate_document_embedding(document)
        assert embedding is not None
        assert len(embedding) == 1536

class TestEmbeddingManager:
    """Integration tests for EmbeddingManager."""
    
    @pytest.fixture
    def embedding_manager(self):
        """Create an EmbeddingManager instance for testing."""
        with patch("src.context.embeddings.settings") as mock_settings, \
             patch("src.context.embeddings.OpenAI") as mock_openai:
            mock_settings.EMBEDDING_PROVIDER = "openai"
            mock_settings.EMBEDDING_MODEL = "text-embedding-ada-002"
            mock_settings.EMBEDDING_DIMENSION = 1536
            mock_settings.EMBEDDING_BATCH_SIZE = 20
            mock_settings.EMBEDDING_CACHE_ENABLED = True
            mock_settings.EMBEDDING_CACHE_SIZE = 1000
            mock_settings.OPENAI_API_KEY = None
            mock_openai.return_value = MagicMock()
            return EmbeddingManager()
    
    @pytest.mark.asyncio
    async def test_generate(self, embedding_manager):
        """Test generating embeddings through manager."""
        with patch.object(embedding_manager.provider, "generate") as mock_generate:
            mock_generate.return_value = [0.1] * 1536
            embedding = await embedding_manager.generate("Test text")
            assert embedding is not None
            assert len(embedding) == 1536
    
    @pytest.mark.asyncio
    async def test_stats(self, embedding_manager):
        """Test getting stats from embedding manager."""
        stats = embedding_manager.get_stats()
        assert "total_requests" in stats
        assert "total_texts" in stats
        assert "cache_hit_rate" in stats
    
    @pytest.mark.asyncio
    async def test_clear_cache(self, embedding_manager):
        """Test clearing the embedding cache."""
        # Add something to cache
        embedding_manager.provider._cache["test"] = [0.1] * 1536
        assert len(embedding_manager.provider._cache) == 1
        
        await embedding_manager.clear_cache()
        assert len(embedding_manager.provider._cache) == 0