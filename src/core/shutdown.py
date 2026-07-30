# src/core/shutdown.py
import signal
import asyncio
import logging
from typing import List, Callable, Awaitable, Any
from contextlib import asynccontextmanager
from src.observability.tracing import tracer

logger = logging.getLogger(__name__)

class ShutdownManager:
    def __init__(self):
        self.shutdown_tasks: List[Callable[[], Awaitable[None]]] = []
        self.is_shutting_down = False
        self._loop = None
        self._register_signal_handlers()
    
    def _register_signal_handlers(self):
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        if self._loop is None:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.error("No running event loop for shutdown")
                return
        asyncio.run_coroutine_threadsafe(self.shutdown(), self._loop)
    
    def register_shutdown_task(self, task: Callable[[], Awaitable[None]]):
        """Register a task to be executed during shutdown."""
        self.shutdown_tasks.append(task)
    
    async def shutdown(self):
        """Execute graceful shutdown."""
        if self.is_shutting_down:
            return
        
        self.is_shutting_down = True
        logger.info("Starting graceful shutdown...")
        
        # Execute shutdown tasks in reverse order
        for task in reversed(self.shutdown_tasks):
            try:
                await task()
                logger.info(f"Shutdown task completed: {task.__name__}")
            except Exception as e:
                logger.error(f"Shutdown task failed: {e}")
        
        logger.info("Graceful shutdown complete")

# Usage in FastAPI app
shutdown_manager = ShutdownManager()

@asynccontextmanager
async def lifespan(app):
    shutdown_manager._loop = asyncio.get_running_loop()
    logger.info("Application starting...")
    yield
    await shutdown_manager.shutdown()

# Register shutdown tasks
async def close_neo4j_connections():
    """Close Neo4j connections."""
    from src.context.graph_rag import graph_rag
    await graph_rag.close()

async def close_qdrant_connections():
    from src.context.vector_rag import VectorRAG
    client = VectorRAG()
    await client.close()

async def close_database_connections():
    """Close database connections."""
    from src.orchestrator.graph import workflow
    # Database connection cleanup

async def close_http_sessions():
    """Close HTTP sessions."""
    from src.integrations.jira import jira_integration
    await jira_integration.close()

# Register tasks
shutdown_manager.register_shutdown_task(close_neo4j_connections)
shutdown_manager.register_shutdown_task(close_qdrant_connections)
shutdown_manager.register_shutdown_task(close_database_connections)
shutdown_manager.register_shutdown_task(close_http_sessions)