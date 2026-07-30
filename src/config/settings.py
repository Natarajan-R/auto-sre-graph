# src/config/settings.py
from typing import Optional, List
from enum import Enum
from pydantic import Field, SecretStr, ConfigDict, field_validator
from pydantic_settings import BaseSettings

from src.models.schemas import Environment

class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Core App Settings
    APP_NAME: str = "Auto-SRE-Graph"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: Environment = Field(default=Environment.DEV)
    LOG_LEVEL: LogLevel = LogLevel.INFO

    # API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_RELOAD: bool = False
    API_WORKERS: int = 4
    API_TIMEOUT: int = 60

    # Database
    POSTGRES_USER: str = Field(default="postgres")
    POSTGRES_PASSWORD: SecretStr = Field(default=SecretStr("postgres"))
    POSTGRES_HOST: str = Field(default="localhost")
    POSTGRES_PORT: int = Field(default=5432)
    POSTGRES_DATABASE: str = Field(default="sre_workflows")
    POSTGRES_POOL_SIZE: int = 10
    POSTGRES_MAX_OVERFLOW: int = 20

    @property
    def postgres_uri(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD.get_secret_value()}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DATABASE}"

    # Neo4j
    NEO4J_URI: str = Field(default="bolt://localhost:7687")
    NEO4J_USER: str = Field(default="neo4j")
    NEO4J_PASSWORD: SecretStr = Field(default=SecretStr("neo4j"))
    NEO4J_DATABASE: str = "neo4j"

    @property
    def neo4j_uri(self) -> str:
        return self.NEO4J_URI

    # Qdrant
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_COLLECTION: str = "runbooks"
    QDRANT_VECTOR_SIZE: int = 1536

    @property
    def qdrant_url(self) -> str:
        return f"http://{self.QDRANT_HOST}:{self.QDRANT_PORT}"

    # LLM
    LLM_PROVIDER: str = "openai"
    OPENAI_API_KEY: Optional[SecretStr] = Field(default=None)
    OPENAI_MODEL: str = "gpt-4"
    ANTHROPIC_API_KEY: Optional[SecretStr] = Field(default=None)
    ANTHROPIC_MODEL: str = "claude-opus-5"
    AZURE_OPENAI_ENDPOINT: Optional[str] = Field(default=None)
    AZURE_OPENAI_API_KEY: Optional[SecretStr] = Field(default=None)
    AZURE_OPENAI_DEPLOYMENT: Optional[str] = Field(default=None)

    LLM_TEMPERATURE: float = 0.1
    LLM_MAX_TOKENS: int = 4096
    LLM_TIMEOUT: int = 30

    # LiteLLM Gateway
    LITELLM_MODEL: str = Field(default="gpt-4o")
    LITELLM_HOST: str = "localhost"
    LITELLM_PORT: int = 4000

    @property
    def litellm_url(self) -> str:
        return f"http://{self.LITELLM_HOST}:{self.LITELLM_PORT}"

    # Embedding settings
    EMBEDDING_PROVIDER: str = Field(default="openai")
    EMBEDDING_MODEL: str = Field(default="text-embedding-3-small")
    EMBEDDING_DIMENSION: int = Field(default=1536)
    EMBEDDING_BATCH_SIZE: int = Field(default=100)
    EMBEDDING_CACHE_ENABLED: bool = Field(default=True)
    EMBEDDING_CACHE_SIZE: int = Field(default=1000)
    COHERE_API_KEY: Optional[SecretStr] = Field(default=None)
    HUGGINGFACE_MODEL: Optional[str] = Field(default=None)

    # Redis
    REDIS_HOST: str = Field(default="localhost")
    REDIS_PORT: int = Field(default=6379)
    REDIS_PASSWORD: Optional[SecretStr] = Field(default=None)

    # ADO
    ADO_ORGANIZATION: Optional[str] = Field(default=None)
    ADO_PROJECT: Optional[str] = Field(default=None)
    ADO_PAT: Optional[SecretStr] = Field(default=None)

    # Jira
    JIRA_URL: str = "https://your-domain.atlassian.net"
    JIRA_USERNAME: Optional[str] = None
    JIRA_API_TOKEN: Optional[SecretStr] = None
    JIRA_PROJECT_KEY: str = "SRE"
    JIRA_ISSUE_TYPE: str = "Incident"
    JIRA_WEBHOOK_SECRET: Optional[SecretStr] = Field(default=None)
    WEBHOOK_SIGNING_SECRET: Optional[SecretStr] = Field(default=None)

    # Observability
    OTEL_ENABLED: bool = True
    OTEL_SERVICE_NAME: str = "auto-sre-graph"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4318"

    LANGCHAIN_TRACING_V2: bool = True
    LANGCHAIN_PROJECT: str = "Auto-SRE"
    LANGCHAIN_ENDPOINT: Optional[str] = None
    LANGCHAIN_API_KEY: Optional[SecretStr] = None

    # Security
    API_KEY: Optional[SecretStr] = None
    JWT_SECRET: Optional[SecretStr] = None
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS: int = Field(default=100)
    RATE_LIMIT_PERIOD: int = Field(default=60)

    # Validation
    ALLOWED_CONTENT_TYPES: List[str] = ["application/json"]
    MAX_PAYLOAD_SIZE: int = 10_485_760
    ALLOWED_SERVICES: List[str] = Field(default_factory=list)
    ALLOWED_ENVIRONMENTS: List[str] = Field(default_factory=list)
    REQUIRE_STACK_TRACE: bool = True

    # Logging
    SYSLOG_ENABLED: bool = Field(default=False)
    SYSLOG_HOST: str = Field(default="localhost")
    SYSLOG_PORT: int = Field(default=514)

    # LLM Provider extras
    GEMINI_API_KEY: Optional[SecretStr] = Field(default=None)
    OLLAMA_BASE_URL: Optional[str] = Field(default=None)

    # Timeouts
    CONTEXT_RETRIEVAL_TIMEOUT: int = 30
    AGENT_TIMEOUT: int = 60
    REMEDIATION_TIMEOUT: int = 300

    @field_validator("ALLOWED_SERVICES", "ALLOWED_ENVIRONMENTS", mode="before")
    @classmethod
    def parse_comma_separated_strings(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("LOG_LEVEL", mode="before")
    @classmethod
    def validate_log_level(cls, v):
        if isinstance(v, str):
            return v.upper()
        return v

settings = Settings()