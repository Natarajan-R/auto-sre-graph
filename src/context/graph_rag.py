# src/context/graph_rag.py
from typing import List, Dict, Any, Optional
import logging
from neo4j import GraphDatabase, AsyncGraphDatabase
from src.config.settings import settings
from src.models.schemas import PipelineAlert

logger = logging.getLogger(__name__)

class GraphRAG:
    def __init__(self):
        self.driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD.get_secret_value())
        )
        self._constraints_initialized = False
    
    async def initialize(self):
        if self._constraints_initialized:
            return
        async with self.driver.session() as session:
            constraints = [
                "CREATE CONSTRAINT IF NOT EXISTS FOR (s:Service) REQUIRE s.name IS UNIQUE",
                "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Deployment) REQUIRE d.id IS UNIQUE",
                "CREATE CONSTRAINT IF NOT EXISTS FOR (i:Incident) REQUIRE i.id IS UNIQUE"
            ]
            for constraint in constraints:
                await session.run(constraint)
        self._constraints_initialized = True
        logger.info("GraphRAG constraints initialized")
    
    async def get_service_topology(self, service_name: str, depth: int = 2) -> Dict[str, Any]:
        await self.initialize()
        try:
            async with self.driver.session() as session:
                upstream_query = """
                MATCH (s:Service {name: $service_name})-[r:DEPENDS_ON*1..$depth]->(up:Service)
                RETURN DISTINCT up.name as name
                """
                downstream_query = """
                MATCH (s:Service {name: $service_name})<-[r:DEPENDS_ON*1..$depth]-(down:Service)
                RETURN DISTINCT down.name as name
                """

                upstream_result = await session.run(upstream_query, service_name=service_name, depth=depth)
                downstream_result = await session.run(downstream_query, service_name=service_name, depth=depth)

                upstream_records = await upstream_result.data()
                downstream_records = await downstream_result.data()

                upstream = sorted([r['name'] for r in upstream_records if r.get('name')])
                downstream = sorted([r['name'] for r in downstream_records if r.get('name')])
                all_deps = sorted(set(upstream + downstream))

                topology = {
                    'service': service_name,
                    'upstream': upstream,
                    'downstream': downstream,
                    'dependencies': all_deps
                }

                logger.info(f"Retrieved topology for {service_name}: "
                           f"{len(upstream)} upstream, {len(downstream)} downstream dependencies")
                return topology

        except Exception as e:
            logger.error(f"Failed to get topology for {service_name}: {e}")
            return {'service': service_name, 'upstream': [], 'downstream': [], 'dependencies': []}
    
    async def get_impacted_services(self, service_name: str) -> List[str]:
        """Get all services impacted by a service failure."""
        try:
            async with self.driver.session() as session:
                query = """
                MATCH (s:Service {name: $service_name})-[r:DEPENDS_ON*1..3]->(impacted)
                RETURN DISTINCT impacted.name as impacted_service
                """
                result = await session.run(query, service_name=service_name)
                records = await result.data()
                
                impacted = [record['impacted_service'] for record in records if record['impacted_service']]
                logger.info(f"Found {len(impacted)} impacted services for {service_name}")
                return impacted
        
        except Exception as e:
            logger.error(f"Failed to get impacted services for {service_name}: {e}")
            return []
    
    async def add_service(self, service_name: str, properties: Dict[str, Any]) -> bool:
        """Add or update a service in the graph."""
        try:
            async with self.driver.session() as session:
                query = """
                MERGE (s:Service {name: $name})
                SET s += $properties
                RETURN s
                """
                result = await session.run(
                    query,
                    name=service_name,
                    properties=properties
                )
                record = await result.single()
                return record is not None
        except Exception as e:
            logger.error(f"Failed to add service {service_name}: {e}")
            return False
    
    async def add_dependency(self, source: str, target: str, dependency_type: str = "DEPENDS_ON") -> bool:
        """Add a dependency between services."""
        try:
            async with self.driver.session() as session:
                query = """
                MATCH (source:Service {name: $source})
                MATCH (target:Service {name: $target})
                MERGE (source)-[r:DEPENDS_ON {type: $dependency_type}]->(target)
                RETURN r
                """
                result = await session.run(
                    query,
                    source=source,
                    target=target,
                    dependency_type=dependency_type
                )
                record = await result.single()
                return record is not None
        except Exception as e:
            logger.error(f"Failed to add dependency {source} -> {target}: {e}")
            return False
    
    async def close(self):
        """Close the database connection."""
        await self.driver.close()