# src/tools/remediation.py
from typing import Dict, Any, Optional, List
import logging
import shlex
import asyncio
from datetime import datetime
from src.config.settings import settings
from src.models.schemas import ActionType
from src.observability.tracing import tracer, trace_span

logger = logging.getLogger(__name__)

ALLOWED_BINARIES = frozenset({
    'kubectl', 'helm', 'git', 'docker', 'systemctl',
})

class RemediationTool:
    def __init__(self):
        self.timeout = settings.REMEDIATION_TIMEOUT
        self.allowed_commands = {
            'rollback': ['kubectl', 'helm', 'git'],
            'restart': ['kubectl', 'docker', 'systemctl'],
            'scale': ['kubectl'],
            'config': ['kubectl'],
        }
    
    @trace_span("remediation.execute")
    async def execute(
        self,
        action: ActionType,
        script: Optional[str],
        service: str,
        environment: str
    ) -> Dict[str, Any]:
        try:
            if environment == "PROD" and action != ActionType.ESCALATE_ONLY:
                logger.warning(f"PROD environment requires manual approval for {action}")
                return {
                    'success': False,
                    'error': 'PROD environment requires manual approval'
                }
            
            if not script:
                return {
                    'success': False,
                    'error': 'No remediation script provided'
                }
            
            parsed = self._parse_and_validate(script, action)
            if parsed is None:
                return {
                    'success': False,
                    'error': 'Script validation failed - unsafe commands detected'
                }
            
            result = await self._execute_command(parsed)
            
            if result['success']:
                logger.info(f"Remediation successful: {action} on {service}")
                await self._update_status(service, "remediated", result)
            else:
                logger.error(f"Remediation failed: {result['error']}")
            
            return result
        
        except Exception as e:
            logger.error(f"Remediation execution failed: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _parse_and_validate(self, script: str, action: ActionType) -> Optional[List[str]]:
        allowed = self.allowed_commands.get(action.value.lower())
        if not allowed:
            logger.error(f"No allowed binaries configured for action {action}")
            return None
        
        try:
            parts = shlex.split(script)
        except ValueError as e:
            logger.warning(f"Failed to parse script: {e}")
            return None
        
        if not parts:
            return None
        
        binary = parts[0].split('/')[-1]
        if binary not in ALLOWED_BINARIES or binary not in allowed:
            logger.warning(f"Binary '{binary}' not allowed for action {action}")
            return None
        
        return parts
    
    async def _execute_command(self, command: List[str]) -> Dict[str, Any]:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                return {
                    'success': False,
                    'error': f'Script execution timed out after {self.timeout}s'
                }
            
            if process.returncode == 0:
                return {
                    'success': True,
                    'output': stdout.decode() if stdout else '',
                    'error': None
                }
            else:
                return {
                    'success': False,
                    'output': stdout.decode() if stdout else '',
                    'error': stderr.decode() if stderr else f'Exit code: {process.returncode}'
                }
        
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def _update_status(self, service: str, status: str, details: Dict[str, Any]):
        logger.info(f"Service {service} status updated to {status}")