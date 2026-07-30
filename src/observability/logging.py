# src/observability/logging.py
import logging
import json
import sys
from datetime import datetime
from typing import Dict, Any, Optional
from logging.handlers import RotatingFileHandler, SysLogHandler
from pythonjsonlogger import jsonlogger
from src.config.settings import settings

class StructuredFormatter(jsonlogger.JsonFormatter):
    """JSON formatter for structured logging."""
    
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        
        # Add standard fields
        log_record['timestamp'] = datetime.utcnow().isoformat()
        log_record['level'] = record.levelname
        log_record['logger'] = record.name
        log_record['module'] = record.module
        log_record['function'] = record.funcName
        log_record['line'] = record.lineno
        
        # Add environment
        log_record['environment'] = settings.ENVIRONMENT.value
        
        # Add service name
        log_record['service'] = settings.APP_NAME
        
        # Add trace ID if available
        if hasattr(record, 'trace_id'):
            log_record['trace_id'] = record.trace_id
        
        # Add request ID if available
        if hasattr(record, 'request_id'):
            log_record['request_id'] = record.request_id

class LoggingManager:
    """Manager for application logging configuration."""
    
    def __init__(self):
        self.loggers = {}
        self._configure_root_logger()
    
    def _configure_root_logger(self):
        """Configure the root logger."""
        root_logger = logging.getLogger()
        root_logger.setLevel(settings.LOG_LEVEL)
        
        # Remove existing handlers
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # Add console handler
        console_handler = self._create_console_handler()
        root_logger.addHandler(console_handler)
        
        # Add file handler
        file_handler = self._create_file_handler()
        root_logger.addHandler(file_handler)
        
        # Add syslog handler
        syslog_handler = self._create_syslog_handler()
        if syslog_handler:
            root_logger.addHandler(syslog_handler)
    
    def _create_console_handler(self) -> logging.Handler:
        """Create console handler with structured formatting."""
        handler = logging.StreamHandler(sys.stdout)
        
        if settings.ENVIRONMENT.value in ['PROD', 'UAT']:
            # Use JSON format in production
            formatter = StructuredFormatter()
        else:
            # Use readable format in development
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
        
        handler.setFormatter(formatter)
        return handler
    
    def _create_file_handler(self) -> logging.Handler:
        """Create rotating file handler."""
        try:
            handler = RotatingFileHandler(
                '/var/log/auto-sre-graph/app.log',
                maxBytes=10485760,  # 10MB
                backupCount=10
            )
            
            if settings.ENVIRONMENT.value in ['PROD', 'UAT']:
                formatter = StructuredFormatter()
            else:
                formatter = logging.Formatter(
                    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S'
                )
            
            handler.setFormatter(formatter)
            return handler
            
        except (PermissionError, OSError) as e:
            # Fall back to console only if file cannot be created
            print(f"Warning: Could not create file handler: {e}")
            return logging.NullHandler()
    
    def _create_syslog_handler(self) -> Optional[logging.Handler]:
        """Create syslog handler if configured."""
        if settings.SYSLOG_ENABLED:
            try:
                handler = SysLogHandler(
                    address=(settings.SYSLOG_HOST, settings.SYSLOG_PORT),
                    facility=SysLogHandler.LOG_LOCAL0
                )
                
                if settings.ENVIRONMENT.value in ['PROD', 'UAT']:
                    formatter = StructuredFormatter()
                else:
                    formatter = logging.Formatter(
                        'auto-sre-graph[%(process)d]: %(levelname)s - %(message)s'
                    )
                
                handler.setFormatter(formatter)
                return handler
                
            except Exception as e:
                print(f"Warning: Could not create syslog handler: {e}")
                return None
        
        return None
    
    def get_logger(self, name: str) -> logging.Logger:
        """
        Get a logger instance.
        
        Args:
            name: Logger name
            
        Returns:
            Logger instance
        """
        if name not in self.loggers:
            logger = logging.getLogger(name)
            self.loggers[name] = logger
        return self.loggers[name]
    
    def set_level(self, level: str):
        """
        Set log level for all loggers.
        
        Args:
            level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        numeric_level = getattr(logging, level.upper(), logging.INFO)
        logging.getLogger().setLevel(numeric_level)
        
        for logger in self.loggers.values():
            logger.setLevel(numeric_level)
    
    def add_context_filter(self, logger: logging.Logger, context: Dict[str, Any]):
        """
        Add a filter to inject context into log records.
        
        Args:
            logger: The logger to add the filter to
            context: Context to inject
        """
        class ContextFilter(logging.Filter):
            def filter(self, record):
                for key, value in context.items():
                    setattr(record, key, value)
                return True
        
        logger.addFilter(ContextFilter())

# Global logger manager
log_manager = LoggingManager()

# Convenience function
def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    return log_manager.get_logger(name)