# src/integrations/ado.py
from typing import Dict, Any, Optional, List
import logging
import json
from datetime import datetime
import aiohttp
import base64
from src.config.settings import settings
from src.observability.tracing import tracer, trace_span

logger = logging.getLogger(__name__)

class ADOIntegration:
    """Azure DevOps integration for pipeline events and operations."""
    
    def __init__(self):
        self.organization = settings.ADO_ORGANIZATION
        self.project = settings.ADO_PROJECT
        self.pat = settings.ADO_PAT.get_secret_value() if settings.ADO_PAT else None
        self.base_url = f"https://dev.azure.com/{self.organization}/{self.project}"
        self.session = None
        
        # Authentication header
        if self.pat:
            auth_string = f":{self.pat}"
            b64_auth = base64.b64encode(auth_string.encode()).decode()
            self.auth_header = f"Basic {b64_auth}"
        else:
            self.auth_header = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if not self.session:
            self.session = aiohttp.ClientSession()
        return self.session
    
    @trace_span("ado.get_pipeline_run")
    async def get_pipeline_run(self, run_id: str) -> Dict[str, Any]:
        """
        Get pipeline run details from ADO.
        
        Args:
            run_id: The pipeline run ID
            
        Returns:
            Pipeline run details
        """
        try:
            url = f"{self.base_url}/_apis/pipelines/1/runs/{run_id}?api-version=7.0"
            headers = self._get_headers()
            
            session = await self._get_session()
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"Retrieved pipeline run {run_id}")
                    return self._parse_pipeline_run(data)
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to get pipeline run {run_id}: {error_text}")
                    return {}
                    
        except Exception as e:
            logger.error(f"Error getting pipeline run {run_id}: {e}")
            raise
    
    @trace_span("ado.get_pipeline_logs")
    async def get_pipeline_logs(self, run_id: str) -> List[str]:
        """
        Get pipeline logs from ADO.
        
        Args:
            run_id: The pipeline run ID
            
        Returns:
            List of log lines
        """
        try:
            url = f"{self.base_url}/_apis/pipelines/1/runs/{run_id}/logs?api-version=7.0"
            headers = self._get_headers()
            
            session = await self._get_session()
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    logs = await response.text()
                    return logs.split('\n')
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to get logs for run {run_id}: {error_text}")
                    return []
                    
        except Exception as e:
            logger.error(f"Error getting logs for run {run_id}: {e}")
            return []
    
    @trace_span("ado.trigger_pipeline")
    async def trigger_pipeline(
        self,
        pipeline_id: str,
        parameters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Trigger a pipeline run in ADO.
        
        Args:
            pipeline_id: The pipeline ID
            parameters: Pipeline parameters
            
        Returns:
            Pipeline run details
        """
        try:
            url = f"{self.base_url}/_apis/pipelines/{pipeline_id}/runs?api-version=7.0"
            headers = self._get_headers()
            
            payload = {
                "resources": {
                    "repositories": {
                        "self": {
                            "refName": "refs/heads/main"
                        }
                    }
                }
            }
            
            if parameters:
                payload["variables"] = parameters
            
            session = await self._get_session()
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"Triggered pipeline {pipeline_id} run {data.get('id')}")
                    return data
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to trigger pipeline {pipeline_id}: {error_text}")
                    return {}
                    
        except Exception as e:
            logger.error(f"Error triggering pipeline {pipeline_id}: {e}")
            raise
    
    @trace_span("ado.get_release")
    async def get_release(self, release_id: str) -> Dict[str, Any]:
        """
        Get release details from ADO.
        
        Args:
            release_id: The release ID
            
        Returns:
            Release details
        """
        try:
            url = f"{self.base_url}/_apis/release/releases/{release_id}?api-version=7.0"
            headers = self._get_headers()
            
            session = await self._get_session()
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"Retrieved release {release_id}")
                    return self._parse_release(data)
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to get release {release_id}: {error_text}")
                    return {}
                    
        except Exception as e:
            logger.error(f"Error getting release {release_id}: {e}")
            raise
    
    @trace_span("ado.get_build")
    async def get_build(self, build_id: str) -> Dict[str, Any]:
        """
        Get build details from ADO.
        
        Args:
            build_id: The build ID
            
        Returns:
            Build details
        """
        try:
            url = f"{self.base_url}/_apis/build/builds/{build_id}?api-version=7.0"
            headers = self._get_headers()
            
            session = await self._get_session()
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"Retrieved build {build_id}")
                    return self._parse_build(data)
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to get build {build_id}: {error_text}")
                    return {}
                    
        except Exception as e:
            logger.error(f"Error getting build {build_id}: {e}")
            raise
    
    @trace_span("ado.create_work_item")
    async def create_work_item(
        self,
        title: str,
        description: str,
        work_item_type: str = "Bug",
        fields: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a work item in ADO.
        
        Args:
            title: Work item title
            description: Work item description
            work_item_type: Type of work item
            fields: Additional fields
            
        Returns:
            Created work item
        """
        try:
            url = f"{self.base_url}/_apis/wit/workitems/${work_item_type}?api-version=7.0"
            headers = self._get_headers()
            
            # Prepare work item fields
            work_item_fields = {
                "System.Title": title,
                "System.Description": description
            }
            
            if fields:
                work_item_fields.update(fields)
            
            # Convert to JSON patch format
            payload = []
            for key, value in work_item_fields.items():
                payload.append({
                    "op": "add",
                    "path": f"/fields/{key}",
                    "value": value
                })
            
            session = await self._get_session()
            async with session.patch(url, headers=headers, json=payload) as response:
                if response.status in [200, 201]:
                    data = await response.json()
                    logger.info(f"Created work item {data.get('id')}")
                    return data
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to create work item: {error_text}")
                    return {}
                    
        except Exception as e:
            logger.error(f"Error creating work item: {e}")
            raise
    
    def _get_headers(self) -> Dict[str, str]:
        """Get request headers."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        if self.auth_header:
            headers["Authorization"] = self.auth_header
        
        return headers
    
    def _parse_pipeline_run(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse pipeline run data."""
        return {
            'id': data.get('id'),
            'name': data.get('name'),
            'status': data.get('status'),
            'result': data.get('result'),
            'created_date': data.get('createdDate'),
            'url': data.get('url'),
            'resources': data.get('resources', {})
        }
    
    def _parse_release(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse release data."""
        return {
            'id': data.get('id'),
            'name': data.get('name'),
            'status': data.get('status'),
            'created_on': data.get('createdOn'),
            'modified_on': data.get('modifiedOn'),
            'artifacts': data.get('artifacts', []),
            'environments': data.get('environments', [])
        }
    
    def _parse_build(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse build data."""
        return {
            'id': data.get('id'),
            'build_number': data.get('buildNumber'),
            'status': data.get('status'),
            'result': data.get('result'),
            'queue_time': data.get('queueTime'),
            'start_time': data.get('startTime'),
            'finish_time': data.get('finishTime'),
            'source_branch': data.get('sourceBranch'),
            'source_version': data.get('sourceVersion'),
            'definition': data.get('definition', {}).get('name')
        }
    
    async def close(self):
        """Close the session."""
        if self.session:
            await self.session.close()