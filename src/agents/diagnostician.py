# src/agents/diagnostician.py
from typing import Dict, Any, Optional, Union, Type, Callable
import logging
import json
from datetime import datetime
import asyncio
from enum import Enum
from src.config.settings import settings
from src.models.schemas import DiagnosticAnalysis, ActionType, PipelineAlert
from src.agents.prompts import SYSTEM_PROMPT
from src.observability.tracing import tracer, trace_span
from src.observability.cost_manager import CostManager

logger = logging.getLogger(__name__)

# Pydantic AI version compatibility layer
try:
    # Try newer versions (>= 0.0.15)
    from pydantic_ai import Agent, ModelRetry, RunContext
    from pydantic_ai.models import Model, ModelRequest, ModelResponse, ModelResponseStream
    from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter
    from pydantic_ai.exceptions import ModelRetryError
except ImportError:
    try:
        # Try mid versions (0.0.10 - 0.0.14)
        from pydantic_ai import Agent, ModelRetry
        from pydantic_ai.models import Model, ModelRequest
        from pydantic_ai.messages import ModelMessage
    except ImportError:
        try:
            # Try older versions (< 0.0.10)
            from pydantic_ai import Agent
            from pydantic_ai.models import Model
        except ImportError:
            # Fallback for very old versions
            from pydantic_ai import Agent
            Agent = Agent

# Try importing known models
try:
    from pydantic_ai.models.openai import OpenAIModel
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.models.gemini import GeminiModel
    from pydantic_ai.models.ollama import OllamaModel
except ImportError:
    try:
        # Alternative import paths
        from pydantic_ai.models import OpenAIModel, AnthropicModel
    except ImportError:
        # Fallback for older versions
        OpenAIModel = None
        AnthropicModel = None
        GeminiModel = None
        OllamaModel = None

# Try LiteLLM integration
try:
    from pydantic_ai.models.litellm import LiteLLMModel
    HAS_LITELLM_MODEL = True
except ImportError:
    try:
        # Alternative import
        from pydantic_ai.models import LiteLLMModel
        HAS_LITELLM_MODEL = True
    except ImportError:
        LiteLLM = None
        HAS_LITELLM_MODEL = False
        logger.warning("LiteLLM model not available in pydantic-ai. Using fallback.")

# Check version
try:
    from pydantic_ai import __version__ as PYDANTIC_AI_VERSION
    logger.info(f"Using pydantic-ai version: {PYDANTIC_AI_VERSION}")
except ImportError:
    PYDANTIC_AI_VERSION = "unknown"

class ModelProvider(str, Enum):
    """Supported model providers."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    OLLAMA = "ollama"
    LITELLM = "litellm"
    AZURE = "azure"

class DiagnosticAgent:
    """
    Pydantic AI Agent for SRE diagnostic analysis.
    Compatible with multiple pydantic-ai versions.
    """
    
    def __init__(self):
        self.cost_manager = CostManager()
        self._agent = None
        self._model = None
        self._version_compatible = self._check_version_compatibility()
        
        # Initialize agent with version-appropriate configuration
        self._initialize_agent()
    
    def _check_version_compatibility(self) -> bool:
        """Check if the pydantic-ai version is compatible."""
        if PYDANTIC_AI_VERSION == "unknown":
            return True  # Assume compatible
        
        # Parse version
        try:
            version_parts = PYDANTIC_AI_VERSION.split('.')
            major = int(version_parts[0])
            minor = int(version_parts[1]) if len(version_parts) > 1 else 0
            
            # Check major version
            if major == 0:
                # Version 0.x should be compatible with our code
                return True
            elif major >= 1:
                # Version 1.x might have breaking changes
                logger.warning(f"pydantic-ai version {PYDANTIC_AI_VERSION} may have breaking changes")
                return True
            else:
                return False
        except (ValueError, IndexError):
            return True
    
    def _initialize_agent(self):
        """Initialize the Pydantic AI agent with version-aware configuration."""
        try:
            # Get model configuration
            model_instance = self._get_model_instance()
            
            # Check if Agent accepts system_prompt parameter
            import inspect
            
            # Try different Agent initialization patterns based on version
            try:
                # Modern pattern: Agent(model, result_type, system_prompt)
                if self._version_compatible:
                    self._agent = Agent(
                        model_instance,
                        output_type=DiagnosticAnalysis,
                        system_prompt=SYSTEM_PROMPT,
                        retries=3
                    )
                else:
                    # Older pattern: Agent(model) with separate configuration
                    self._agent = Agent(model_instance)
                    # Set system prompt differently for older versions
                    self._set_system_prompt_legacy()
                    
            except TypeError as e:
                logger.warning(f"Agent initialization with system_prompt failed: {e}")
                # Fallback: Initialize without system_prompt
                try:
                    self._agent = Agent(
                        model_instance,
                        output_type=DiagnosticAnalysis,
                        retries=3
                    )
                except TypeError:
                    # Oldest version: Agent(model) only
                    self._agent = Agent(model_instance)
                
                # Set system prompt separately if possible
                self._set_system_prompt_legacy()
            
            logger.info(f"DiagnosticAgent initialized with {settings.LLM_PROVIDER}")
            
        except Exception as e:
            logger.error(f"Failed to initialize DiagnosticAgent: {e}")
            # Create fallback agent without model
            self._agent = None
            raise
    
    def _get_model_instance(self):
        """Get the appropriate model instance based on configuration."""
        provider = settings.LLM_PROVIDER
        
        if provider == ModelProvider.OPENAI:
            return self._create_openai_model()
        elif provider == ModelProvider.ANTHROPIC:
            return self._create_anthropic_model()
        elif provider == ModelProvider.GEMINI:
            return self._create_gemini_model()
        elif provider == ModelProvider.OLLAMA:
            return self._create_ollama_model()
        elif provider == ModelProvider.LITELLM:
            return self._create_litellm_model()
        elif provider == ModelProvider.AZURE:
            return self._create_azure_model()
        else:
            # Default to OpenAI
            logger.warning(f"Unknown provider {provider}, falling back to OpenAI")
            return self._create_openai_model()
    
    def _create_openai_model(self):
        """Create OpenAI model instance."""
        if OpenAIModel is None:
            # Fallback: use string-based model name
            try:
                # Try newer API
                return f"openai:{settings.OPENAI_MODEL}"
            except:
                # Try older API
                return settings.OPENAI_MODEL
        
        try:
            # Modern API
            return OpenAIModel(
                model_name=settings.OPENAI_MODEL,
                api_key=settings.OPENAI_API_KEY.get_secret_value() if settings.OPENAI_API_KEY else None
            )
        except TypeError:
            # Older API
            return OpenAIModel(settings.OPENAI_MODEL)
    
    def _create_anthropic_model(self):
        """Create Anthropic model instance."""
        if AnthropicModel is None:
            return f"anthropic:{settings.ANTHROPIC_MODEL}"
        
        try:
            return AnthropicModel(
                model_name=settings.ANTHROPIC_MODEL,
                api_key=settings.ANTHROPIC_API_KEY.get_secret_value() if settings.ANTHROPIC_API_KEY else None
            )
        except TypeError:
            return AnthropicModel(settings.ANTHROPIC_MODEL)
    
    def _create_gemini_model(self):
        """Create Gemini model instance."""
        if GeminiModel is None:
            return "gemini:gemini-1.5-pro"
        
        try:
            return GeminiModel(
                model_name="gemini-1.5-pro",
                api_key=settings.GEMINI_API_KEY.get_secret_value() if settings.GEMINI_API_KEY else None
            )
        except TypeError:
            return GeminiModel("gemini-1.5-pro")
    
    def _create_ollama_model(self):
        """Create Ollama model instance."""
        if OllamaModel is None:
            return "ollama:llama2"
        
        try:
            return OllamaModel(
                model_name="llama2",
                base_url=settings.OLLAMA_BASE_URL
            )
        except TypeError:
            return OllamaModel("llama2")
    
    def _create_litellm_model(self):
        """Create LiteLLM model instance."""
        if HAS_LITELLM_MODEL and LiteLLMModel is not None:
            try:
                return LiteLLMModel(
                    model=settings.LITELLM_MODEL,
                    api_base=settings.litellm_url
                )
            except TypeError:
                return LiteLLMModel(settings.LITELLM_MODEL)
        else:
            # Fallback: Use OpenAI with LiteLLM proxy
            logger.info("Using OpenAI model with LiteLLM proxy")
            try:
                return OpenAIModel(
                    model_name="gpt-4",
                    api_base=settings.litellm_url
                )
            except:
                return "openai:gpt-4"
    
    def _create_azure_model(self):
        """Create Azure OpenAI model instance."""
        if OpenAIModel is None:
            return f"azure:{settings.AZURE_OPENAI_DEPLOYMENT}"
        
        try:
            return OpenAIModel(
                model_name=settings.AZURE_OPENAI_DEPLOYMENT,
                api_key=settings.AZURE_OPENAI_API_KEY.get_secret_value() if settings.AZURE_OPENAI_API_KEY else None,
                api_base=settings.AZURE_OPENAI_ENDPOINT,
                api_version="2024-02-15-preview"
            )
        except TypeError:
            return OpenAIModel(settings.AZURE_OPENAI_DEPLOYMENT)
    
    def _set_system_prompt_legacy(self):
        """Set system prompt for older pydantic-ai versions."""
        if hasattr(self._agent, 'system_prompt'):
            try:
                self._agent.system_prompt = SYSTEM_PROMPT
            except:
                pass
        elif hasattr(self._agent, 'set_system_prompt'):
            try:
                self._agent.set_system_prompt(SYSTEM_PROMPT)
            except:
                pass
    
    @trace_span("agent.analyze")
    async def analyze(
        self,
        alert: PipelineAlert,
        vector_context: list,
        graph_topology: dict
    ) -> DiagnosticAnalysis:
        """
        Analyze the alert with context and return diagnostic analysis.
        
        Args:
            alert: The pipeline alert to analyze
            vector_context: Retrieved runbooks and historical incidents
            graph_topology: Service dependency graph information
            
        Returns:
            DiagnosticAnalysis object with structured analysis
        """
        try:
            # Prepare the prompt with all context
            prompt = self._build_prompt(alert, vector_context, graph_topology)
            
            # Select model based on complexity and cost
            model_id = self.cost_manager.optimize_model_selection(
                required_complexity='high' if alert.severity.value in ['CRITICAL', 'HIGH'] else 'medium'
            )
            
            # Check if agent is available
            if self._agent is None:
                logger.warning("Agent not initialized, using fallback analysis")
                return self._create_fallback_analysis(alert)
            
            # Execute the agent based on version
            try:
                if hasattr(self._agent, 'run'):
                    result = await self._agent.run(prompt)
                    analysis = result.data if hasattr(result, 'data') else result
                elif hasattr(self._agent, 'run_sync'):
                    result = await asyncio.to_thread(self._agent.run_sync, prompt)
                    analysis = result.data if hasattr(result, 'data') else result
                else:
                    analysis = await self._agent.process(prompt)
                
            except Exception as e:
                logger.error(f"Agent execution failed: {e}")
                # Try fallback with simpler model
                analysis = await self._fallback_analysis(prompt, alert)
            
            # Validate analysis
            if not isinstance(analysis, DiagnosticAnalysis):
                try:
                    # Try to convert if it's a dict
                    if isinstance(analysis, dict):
                        analysis = DiagnosticAnalysis(**analysis)
                    else:
                        raise ValueError(f"Unexpected result type: {type(analysis)}")
                except Exception as e:
                    logger.error(f"Failed to parse analysis result: {e}")
                    return self._create_fallback_analysis(alert)
            
            # Record usage for cost tracking
            self._record_usage(analysis)
            
            logger.info(f"Analysis completed for {alert.alert_id}. Confidence: {analysis.confidence_score}")
            return analysis
            
        except Exception as e:
            logger.error(f"Agent analysis failed for {alert.alert_id}: {e}")
            return self._create_fallback_analysis(alert)
    
    @trace_span("agent.fallback_analysis")
    async def _fallback_analysis(self, prompt: str, alert: PipelineAlert) -> DiagnosticAnalysis:
        """Fallback analysis when primary agent fails."""
        try:
            # Try using a simpler, more reliable model
            if settings.LLM_PROVIDER != "openai":
                # Try OpenAI as fallback
                fallback_model = self._create_openai_model()
                try:
                    fallback_agent = Agent(fallback_model, output_type=DiagnosticAnalysis)
                    if hasattr(fallback_agent, 'run'):
                        result = await fallback_agent.run(prompt)
                    else:
                        result = await asyncio.to_thread(fallback_agent.run_sync, prompt)
                    if hasattr(result, 'data'):
                        return result.data
                    return result
                except Exception as e:
                    logger.error(f"Fallback agent also failed: {e}")
            
            # If all else fails, create a basic analysis
            return self._create_fallback_analysis(alert)
            
        except Exception as e:
            logger.error(f"Fallback analysis failed: {e}")
            return self._create_fallback_analysis(alert)
    
    def _create_fallback_analysis(self, alert: PipelineAlert) -> DiagnosticAnalysis:
        """Create a safe fallback analysis when the agent fails."""
        return DiagnosticAnalysis(
            root_cause_summary=f"Agent analysis unavailable for {alert.service_name}. Manual investigation required.",
            detailed_analysis="The AI diagnostic agent encountered an error and could not complete the analysis. Please investigate manually.",
            historical_matches_found=False,
            confidence_score=0.3,
            proposed_action=ActionType.ESCALATE_ONLY,
            remediation_script=None,
            upstream_dependencies=[],
            downstream_dependencies=[]
        )
    
    def _build_prompt(self, alert: PipelineAlert, vector_context: list, graph_topology: dict) -> str:
        """Build the prompt for the agent with all context."""
        prompt_parts = []
        
        # Alert details
        prompt_parts.append("=== ALERT DETAILS ===")
        prompt_parts.append(f"Alert ID: {alert.alert_id}")
        prompt_parts.append(f"Service: {alert.service_name}")
        prompt_parts.append(f"Environment: {alert.environment}")
        prompt_parts.append(f"Severity: {alert.severity}")
        prompt_parts.append(f"Timestamp: {alert.timestamp}")
        prompt_parts.append(f"Error Message: {alert.error_message}")
        prompt_parts.append(f"Stack Trace: {alert.stack_trace or 'None provided'}")
        prompt_parts.append(f"Commit Hash: {alert.git_commit_hash or 'Unknown'}")
        prompt_parts.append(f"Service Version: {alert.service_version or 'Unknown'}")
        
        # Additional context
        if alert.additional_context:
            prompt_parts.append("=== ADDITIONAL CONTEXT ===")
            prompt_parts.append(json.dumps(alert.additional_context, indent=2))
        
        # Graph topology
        prompt_parts.append("\n=== TOPOLOGICAL DEPENDENCIES (GraphRAG) ===")
        prompt_parts.append(json.dumps(graph_topology, indent=2))
        
        # Vector context
        prompt_parts.append("\n=== HISTORICAL RUNBOOKS & INCIDENTS (Vector RAG) ===")
        if vector_context:
            for idx, context in enumerate(vector_context, 1):
                if isinstance(context, dict):
                    prompt_parts.append(f"\nMatch {idx}:")
                    # Limit context size to avoid token overflow
                    context_str = json.dumps(context, indent=2)
                    if len(context_str) > 2000:
                        context_str = context_str[:2000] + "... (truncated)"
                    prompt_parts.append(context_str)
                else:
                    prompt_parts.append(f"\nMatch {idx}: {str(context)[:500]}")
        else:
            prompt_parts.append("\nNo historical matches found.")
        
        return "\n".join(prompt_parts)
    
    def _record_usage(self, analysis: DiagnosticAnalysis):
        """Record LLM usage for cost tracking."""
        try:
            # Estimate token usage based on analysis complexity
            estimated_input_tokens = 2000  # Approximate
            estimated_output_tokens = len(str(analysis)) // 4  # Rough estimate
            
            self.cost_manager.record_usage(
                model=settings.LLM_PROVIDER,
                input_tokens=estimated_input_tokens,
                output_tokens=estimated_output_tokens
            )
        except Exception as e:
            logger.debug(f"Failed to record usage: {e}")
    
    async def batch_analyze(
        self,
        alerts: list,
        contexts: list
    ) -> list:
        """
        Analyze multiple alerts in batch.
        
        Args:
            alerts: List of PipelineAlert objects
            contexts: List of context dicts with 'vector' and 'graph' keys
            
        Returns:
            List of DiagnosticAnalysis objects
        """
        tasks = []
        for alert, context in zip(alerts, contexts):
            task = self.analyze(
                alert,
                context.get('vector', []),
                context.get('graph', {})
            )
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle failures
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Batch analysis failed for alert {i}: {result}")
                processed_results.append(
                    DiagnosticAnalysis(
                        root_cause_summary=f"Batch analysis failed: {str(result)[:100]}",
                        historical_matches_found=False,
                        confidence_score=0.3,
                        proposed_action=ActionType.ESCALATE_ONLY,
                        remediation_script=None
                    )
                )
            else:
                processed_results.append(result)
        
        return processed_results
    
    async def stream_analysis(
        self,
        alert: PipelineAlert,
        vector_context: list,
        graph_topology: dict
    ):
        """
        Stream the analysis process for real-time feedback.
        
        Args:
            alert: The pipeline alert to analyze
            vector_context: Retrieved runbooks and historical incidents
            graph_topology: Service dependency graph information
            
        Yields:
            Analysis steps and progress updates
        """
        try:
            # Prepare the prompt
            prompt = self._build_prompt(alert, vector_context, graph_topology)
            
            # Check if streaming is supported
            if hasattr(self._agent, 'stream'):
                async for chunk in self._agent.stream(prompt):
                    yield {
                        'type': 'chunk',
                        'content': chunk,
                        'timestamp': datetime.utcnow().isoformat()
                    }
            else:
                # Fallback: regular analysis
                analysis = await self.analyze(alert, vector_context, graph_topology)
                yield {
                    'type': 'complete',
                    'analysis': analysis.dict(),
                    'timestamp': datetime.utcnow().isoformat()
                }
                
        except Exception as e:
            logger.error(f"Stream analysis failed: {e}")
            yield {
                'type': 'error',
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat()
            }

# Optional: Version info for debugging
def get_version_info() -> Dict[str, Any]:
    """Get version information for debugging."""
    return {
        'pydantic_ai_version': PYDANTIC_AI_VERSION,
        'has_openai_model': OpenAIModel is not None,
        'has_anthropic_model': AnthropicModel is not None,
        'has_gemini_model': GeminiModel is not None,
        'has_ollama_model': OllamaModel is not None,
        'has_litellm_model': HAS_LITELLM_MODEL,
        'provider': settings.LLM_PROVIDER,
        'model': settings.OPENAI_MODEL
    }