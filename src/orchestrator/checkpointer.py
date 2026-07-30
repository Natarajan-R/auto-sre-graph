# src/orchestrator/checkpointer.py
from typing import Optional, Dict, Any, List, AsyncIterator
import logging
import json
from datetime import datetime, timedelta
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from src.config.settings import settings
from src.observability.tracing import tracer, trace_span

logger = logging.getLogger(__name__)

class CheckpointerManager:
    """
    Advanced checkpoint manager for LangGraph workflows.
    Provides connection pooling, monitoring, and management features.
    """
    
    def __init__(self):
        self._pool: Optional[AsyncConnectionPool] = None
        self._checkpointer: Optional[AsyncPostgresSaver] = None
        self._initialized = False
        self._max_connections = settings.POSTGRES_POOL_SIZE
        self._min_connections = 5
        
        # Statistics
        self.stats = {
            'checkpoints_created': 0,
            'checkpoints_loaded': 0,
            'checkpoints_deleted': 0,
            'errors': 0,
            'last_checkpoint_time': None
        }
    
    async def initialize(self) -> AsyncPostgresSaver:
        """Initialize the checkpointer with connection pooling."""
        if self._initialized and self._checkpointer:
            return self._checkpointer
        
        try:
            # Create connection pool
            self._pool = AsyncConnectionPool(
                conninfo=settings.postgres_uri,
                min_size=self._min_connections,
                max_size=self._max_connections,
                timeout=30,
                reconnect_timeout=5,
                max_lifetime=3600,
                max_idle=300,
                check=AsyncConnectionPool.check_connection,
                kwargs={"autocommit": True}
            )
            await self._pool.open()
            await self._pool.wait()
            
            # Initialize checkpointer
            self._checkpointer = AsyncPostgresSaver(self._pool)
            await self._checkpointer.setup()
            
            self._initialized = True
            logger.info(f"Checkpointer initialized with pool size {self._max_connections}")
            
            # Start health check task
            asyncio.create_task(self._health_check())
            
            return self._checkpointer
            
        except Exception as e:
            logger.error(f"Failed to initialize checkpointer: {e}")
            self.stats['errors'] += 1
            raise
    
    async def get_checkpointer(self) -> AsyncPostgresSaver:
        """Get the initialized checkpointer."""
        if not self._initialized:
            await self.initialize()
        return self._checkpointer
    
    @trace_span("checkpointer.save")
    async def save_checkpoint(
        self,
        thread_id: str,
        checkpoint_data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Save a checkpoint with additional metadata.
        
        Args:
            thread_id: The thread ID
            checkpoint_data: The checkpoint data to save
            metadata: Additional metadata for the checkpoint
            
        Returns:
            Checkpoint ID
        """
        try:
            checkpointer = await self.get_checkpointer()
            config = {"configurable": {"thread_id": thread_id}}
            
            # Save checkpoint
            # Note: This is a simplified approach - actual implementation depends on LangGraph API
            checkpoint_id = await checkpointer.put(
                config,
                checkpoint_data,
                metadata or {}
            )
            
            self.stats['checkpoints_created'] += 1
            self.stats['last_checkpoint_time'] = datetime.utcnow().isoformat()
            
            logger.debug(f"Checkpoint saved for thread {thread_id}")
            return checkpoint_id
            
        except Exception as e:
            logger.error(f"Failed to save checkpoint for {thread_id}: {e}")
            self.stats['errors'] += 1
            raise
    
    @trace_span("checkpointer.load")
    async def load_checkpoint(
        self,
        thread_id: str,
        checkpoint_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Load a checkpoint by thread ID.
        
        Args:
            thread_id: The thread ID
            checkpoint_id: Optional specific checkpoint ID
            
        Returns:
            Checkpoint data or None if not found
        """
        try:
            checkpointer = await self.get_checkpointer()
            config = {"configurable": {"thread_id": thread_id}}
            
            # Load checkpoint
            if checkpoint_id:
                checkpoint = await checkpointer.get_tuple(config, checkpoint_id)
            else:
                checkpoint = await checkpointer.get_tuple(config)
            
            self.stats['checkpoints_loaded'] += 1
            
            if checkpoint:
                logger.debug(f"Checkpoint loaded for thread {thread_id}")
                return checkpoint
            else:
                logger.debug(f"No checkpoint found for thread {thread_id}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to load checkpoint for {thread_id}: {e}")
            self.stats['errors'] += 1
            return None
    
    @trace_span("checkpointer.delete")
    async def delete_checkpoint(self, thread_id: str, checkpoint_id: Optional[str] = None) -> bool:
        """
        Delete a checkpoint.
        
        Args:
            thread_id: The thread ID
            checkpoint_id: Optional specific checkpoint ID
            
        Returns:
            True if deleted, False otherwise
        """
        try:
            checkpointer = await self.get_checkpointer()
            config = {"configurable": {"thread_id": thread_id}}
            
            # Delete checkpoint
            if checkpoint_id:
                await checkpointer.delete(config, checkpoint_id)
            else:
                await checkpointer.delete(config)
            
            self.stats['checkpoints_deleted'] += 1
            logger.debug(f"Checkpoint deleted for thread {thread_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete checkpoint for {thread_id}: {e}")
            self.stats['errors'] += 1
            return False
    
    async def list_checkpoints(
        self,
        thread_id: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        List checkpoints for a thread.
        
        Args:
            thread_id: The thread ID
            limit: Maximum number of checkpoints to return
            
        Returns:
            List of checkpoint metadata
        """
        try:
            checkpointer = await self.get_checkpointer()
            config = {"configurable": {"thread_id": thread_id}}
            
            # Get checkpoint history
            history = []
            async for checkpoint in checkpointer.list(config, limit=limit):
                history.append({
                    'checkpoint_id': checkpoint.id,
                    'timestamp': checkpoint.timestamp.isoformat(),
                    'metadata': checkpoint.metadata,
                    'parent_id': checkpoint.parent_id
                })
            
            logger.debug(f"Listed {len(history)} checkpoints for thread {thread_id}")
            return history
            
        except Exception as e:
            logger.error(f"Failed to list checkpoints for {thread_id}: {e}")
            self.stats['errors'] += 1
            return []
    
    async def cleanup_old_checkpoints(
        self,
        older_than_days: int = 30
    ) -> int:
        """
        Clean up old checkpoints.
        
        Args:
            older_than_days: Delete checkpoints older than this many days
            
        Returns:
            Number of checkpoints deleted
        """
        try:
            # This would require a custom query or API
            # Implement based on your specific LangGraph version
            cutoff = datetime.utcnow() - timedelta(days=older_than_days)
            
            # Placeholder - actual implementation depends on LangGraph API
            deleted_count = 0
            logger.info(f"Cleaned up {deleted_count} checkpoints older than {older_than_days} days")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup old checkpoints: {e}")
            self.stats['errors'] += 1
            return 0
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get checkpointer statistics."""
        pool_stats = {}
        if self._pool:
            pool_stats = {
                'size': self._pool.size,
                'available': self._pool.available,
                'in_use': self._pool.used
            }
        
        return {
            **self.stats,
            'pool': pool_stats,
            'initialized': self._initialized
        }
    
    async def _health_check(self):
        """Periodic health check for the checkpointer."""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                
                # Test connection
                if self._pool:
                    async with self._pool.connection() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute("SELECT 1")
                
                logger.debug("Checkpointer health check passed")
                
            except Exception as e:
                logger.error(f"Checkpointer health check failed: {e}")
                self.stats['errors'] += 1
                
                # Try to reconnect
                try:
                    await self._reconnect()
                except Exception as reconnect_error:
                    logger.error(f"Failed to reconnect: {reconnect_error}")
    
    async def _reconnect(self):
        """Reconnect the checkpointer if connection is lost."""
        logger.info("Attempting to reconnect checkpointer...")
        
        self._initialized = False
        self._pool = None
        self._checkpointer = None
        
        await self.initialize()
        logger.info("Checkpointer reconnected successfully")
    
    async def close(self):
        """Close the checkpointer and connection pool."""
        try:
            if self._pool:
                await self._pool.close()
                logger.info("Checkpointer connection pool closed")
            
            self._initialized = False
            self._pool = None
            self._checkpointer = None
            
        except Exception as e:
            logger.error(f"Error closing checkpointer: {e}")

# Global instance
checkpointer_manager = CheckpointerManager()