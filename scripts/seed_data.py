#!/usr/bin/env python3
# scripts/seed_data.py
# Seed database with sample data for development and testing

import asyncio
import json
import logging
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path
import random
import psycopg
from psycopg.rows import dict_row
from typing import Dict, Any, List, Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from src.config.settings import settings
from src.models.schemas import PipelineAlert, Environment, AlertSeverity, ActionType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DataSeeder:
    """Seed database with sample data."""
    
    def __init__(self):
        self.conn = None
        self.services = [
            "auth-service", "payment-service", "order-service", 
            "user-service", "notification-service", "inventory-service",
            "cart-service", "catalog-service", "shipping-service",
            "analytics-service", "logging-service", "monitoring-service"
        ]
        self.environments = ["DEV", "SIT", "UAT", "PROD"]
        self.severities = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
        self.actions = ["ROLLBACK", "RESTART_SERVICE", "ESCALATE_ONLY", "SCALE_UP", "CONFIG_UPDATE"]
        
        self.error_templates = [
            "Connection timeout to {service}: Connection refused",
            "Database connection pool exhausted for {service}",
            "Memory limit exceeded for {service} pod",
            "CPU throttling detected in {service}",
            "Service {service} is unreachable",
            "Authentication failed for {service}",
            "Invalid configuration detected in {service}",
            "Disk space critical for {service}",
            "Network latency spike detected in {service}",
            "SSL certificate expired for {service}"
        ]
        
        self.root_causes = [
            "Database connection pool exhausted due to slow queries",
            "Memory leak in service causing OOM kills",
            "Network partition between services",
            "Configuration drift in production",
            "Dependency service failure cascading",
            "Resource limits insufficient for workload",
            "Deployment rollback due to failed health checks",
            "Third-party API rate limit exceeded",
            "DNS resolution failure",
            "Disk I/O bottleneck"
        ]
    
    async def connect(self):
        """Connect to database."""
        try:
            self.conn = await psycopg.AsyncConnection.connect(
                settings.postgres_uri,
                row_factory=dict_row
            )
            logger.info("Connected to database")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise
    
    async def close(self):
        """Close database connection."""
        if self.conn:
            await self.conn.close()
            logger.info("Database connection closed")
    
    async def seed_checkpoints(self, count: int = 10):
        """Seed checkpoint data."""
        logger.info(f"Seeding {count} checkpoints...")
        
        for i in range(count):
            thread_id = f"THREAD-{i+1:05d}"
            checkpoint_id = f"CP-{i+1:05d}"
            
            checkpoint_data = {
                "v": 1,
                "state": {
                    "alert": {
                        "alert_id": f"ALERT-{i+1:05d}",
                        "service_name": random.choice(self.services),
                        "environment": random.choice(self.environments),
                        "error_message": random.choice(self.error_templates).format(
                            service=random.choice(self.services)
                        )
                    },
                    "analysis": {
                        "root_cause_summary": random.choice(self.root_causes),
                        "confidence_score": round(random.uniform(0.5, 0.95), 2),
                        "proposed_action": random.choice(self.actions)
                    }
                },
                "ts": datetime.utcnow().isoformat()
            }
            
            await self.conn.execute(
                """
                INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, checkpoint, metadata)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id) DO UPDATE 
                SET checkpoint = EXCLUDED.checkpoint
                """,
                (thread_id, "", checkpoint_id, json.dumps(checkpoint_data), "{}")
            )
        
        logger.info(f"✓ Seeded {count} checkpoints")
    
    async def seed_audit_events(self, count: int = 50):
        """Seed audit events."""
        logger.info(f"Seeding {count} audit events...")
        
        actions = [
            "ALERT_RECEIVED", "ALERT_FILTERED", "CONTEXT_RETRIEVED",
            "DIAGNOSIS_COMPLETE", "JIRA_TICKET_CREATED", "HUMAN_APPROVED",
            "REMEDIATION_EXECUTED", "WORKFLOW_ERROR", "WORKFLOW_COMPLETED"
        ]
        
        now = datetime.utcnow()
        
        for i in range(count):
            timestamp = now - timedelta(days=random.randint(0, 30), hours=random.randint(0, 23))
            
            await self.conn.execute(
                """
                INSERT INTO audit_events (event_id, action, actor, target, timestamp, environment, source_ip, details)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    f"EVT-{i+1:08d}",
                    random.choice(actions),
                    random.choice(["system", "ado_pipeline", "human"]),
                    f"TARGET-{i+1:05d}",
                    timestamp,
                    random.choice(self.environments),
                    f"192.168.{random.randint(0, 255)}.{random.randint(0, 255)}",
                    json.dumps({
                        "service": random.choice(self.services),
                        "details": f"Sample event {i+1}"
                    })
                )
            )
        
        logger.info(f"✓ Seeded {count} audit events")
    
    async def seed_workflows(self, count: int = 20):
        """Seed workflow instances."""
        logger.info(f"Seeding {count} workflows...")
        
        statuses = [
            "PROCESSING", "WAITING_ON_HUMAN", "APPROVAL_PROCESSED",
            "REMEDIATION_SUCCESSFUL", "REMEDIATION_FAILED",
            "ESCALATED", "ERROR", "COMPLETED"
        ]
        
        now = datetime.utcnow()
        
        for i in range(count):
            started_at = now - timedelta(
                days=random.randint(0, 7),
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59)
            )
            completed_at = started_at + timedelta(
                minutes=random.randint(1, 60)
            ) if random.random() > 0.3 else None
            
            service = random.choice(self.services)
            error_template = random.choice(self.error_templates)
            
            await self.conn.execute(
                """
                INSERT INTO workflows (
                    thread_id, alert_id, service_name, environment, status,
                    jira_ticket_id, started_at, completed_at, updated_at,
                    metadata, error_count, error_messages
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    f"THREAD-{i+1:05d}",
                    f"ALERT-{i+1:05d}",
                    service,
                    random.choice(self.environments),
                    random.choice(statuses),
                    f"SRE-{i+1000:04d}" if random.random() > 0.3 else None,
                    started_at,
                    completed_at,
                    started_at,
                    json.dumps({
                        "error_message": error_template.format(service=service),
                        "stack_trace": f"Traceback: {error_template.format(service=service)}"
                    }),
                    random.randint(0, 3),
                    [] if random.random() > 0.2 else ["Sample error message"]
                )
            )
        
        logger.info(f"✓ Seeded {count} workflows")
    
    async def seed_incidents(self, count: int = 30):
        """Seed incident history."""
        logger.info(f"Seeding {count} incidents...")
        
        statuses = ["OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED", "ESCALATED"]
        now = datetime.utcnow()
        
        for i in range(count):
            created_at = now - timedelta(
                days=random.randint(0, 60),
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59)
            )
            resolved_at = created_at + timedelta(
                minutes=random.randint(5, 120)
            ) if random.random() > 0.2 else None
            
            service = random.choice(self.services)
            error_template = random.choice(self.error_templates)
            
            await self.conn.execute(
                """
                INSERT INTO incidents (
                    incident_id, alert_id, service_name, environment, severity,
                    error_message, stack_trace, root_cause_summary,
                    confidence_score, proposed_action, remediation_script,
                    resolution_time_seconds, jira_ticket_id, status,
                    created_at, resolved_at, metadata
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    f"INC-{i+1:06d}",
                    f"ALERT-{i+1:05d}",
                    service,
                    random.choice(self.environments),
                    random.choice(self.severities),
                    error_template.format(service=service),
                    f"Traceback: {error_template.format(service=service)}",
                    random.choice(self.root_causes),
                    round(random.uniform(0.3, 0.95), 2),
                    random.choice(self.actions),
                    "kubectl rollout undo deployment/" + service if random.random() > 0.5 else None,
                    int((resolved_at - created_at).total_seconds()) if resolved_at else None,
                    f"SRE-{i+1000:04d}" if random.random() > 0.3 else None,
                    random.choice(statuses),
                    created_at,
                    resolved_at,
                    json.dumps({
                        "tags": [f"tag_{random.randint(1, 5)}" for _ in range(random.randint(0, 3))]
                    })
                )
            )
        
        logger.info(f"✓ Seeded {count} incidents")
    
    async def seed_sla_metrics(self):
        """Seed SLA metrics for services."""
        logger.info("Seeding SLA metrics...")
        
        now = datetime.utcnow()
        
        for service in self.services:
            for env in self.environments:
                for days_ago in range(0, 30, 7):
                    date = now - timedelta(days=days_ago)
                    date = date.replace(hour=0, minute=0, second=0, microsecond=0)
                    
                    total_incidents = random.randint(0, 50)
                    resolved_incidents = int(total_incidents * random.uniform(0.7, 1.0))
                    
                    await self.conn.execute(
                        """
                        INSERT INTO service_sla_metrics (
                            service_name, environment, metric_date,
                            total_incidents, resolved_incidents,
                            total_downtime_seconds, avg_resolution_time_seconds,
                            p95_resolution_time_seconds, p99_resolution_time_seconds,
                            rollback_count, escalation_count, success_rate
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (service_name, environment, metric_date) DO UPDATE SET
                            total_incidents = EXCLUDED.total_incidents,
                            resolved_incidents = EXCLUDED.resolved_incidents,
                            success_rate = EXCLUDED.success_rate
                        """,
                        (
                            service,
                            env,
                            date,
                            total_incidents,
                            resolved_incidents,
                            random.randint(0, 3600),
                            random.randint(60, 600),
                            random.randint(300, 900),
                            random.randint(600, 1200),
                            random.randint(0, 20),
                            random.randint(0, 10),
                            round((resolved_incidents / max(1, total_incidents)) * 100, 2)
                        )
                    )
        
        logger.info(f"✓ Seeded SLA metrics for {len(self.services)} services")
    
    async def seed_llm_usage(self, count: int = 100):
        """Seed LLM usage data."""
        logger.info(f"Seeding {count} LLM usage records...")
        
        models = ["gpt-4", "gpt-3.5-turbo", "claude-3-opus", "claude-3-sonnet"]
        model_costs = {
            "gpt-4": {"input": 0.03, "output": 0.06},
            "gpt-3.5-turbo": {"input": 0.001, "output": 0.002},
            "claude-3-opus": {"input": 0.015, "output": 0.075},
            "claude-3-sonnet": {"input": 0.003, "output": 0.015}
        }
        
        now = datetime.utcnow()
        
        for i in range(count):
            model = random.choice(models)
            input_tokens = random.randint(100, 2000)
            output_tokens = random.randint(50, 1000)
            total_tokens = input_tokens + output_tokens
            
            cost = (
                (input_tokens / 1000) * model_costs[model]["input"] +
                (output_tokens / 1000) * model_costs[model]["output"]
            )
            
            timestamp = now - timedelta(
                days=random.randint(0, 14),
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59)
            )
            
            await self.conn.execute(
                """
                INSERT INTO llm_usage (
                    request_id, model, input_tokens, output_tokens,
                    total_tokens, cost, environment, service_name,
                    alert_id, timestamp, metadata
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    f"REQ-{i+1:08d}",
                    model,
                    input_tokens,
                    output_tokens,
                    total_tokens,
                    round(cost, 6),
                    random.choice(self.environments),
                    random.choice(self.services),
                    f"ALERT-{random.randint(1, 100):05d}",
                    timestamp,
                    json.dumps({
                        "prompt": "Sample prompt",
                        "temperature": 0.1
                    })
                )
            )
        
        logger.info(f"✓ Seeded {count} LLM usage records")
    
    async def seed_alert_dedup(self, count: int = 20):
        """Seed alert deduplication data."""
        logger.info(f"Seeding {count} alert dedup records...")
        
        now = datetime.utcnow()
        
        for i in range(count):
            service = random.choice(self.services)
            fingerprint = f"FP-{hash(service + str(i)):016x}"
            
            await self.conn.execute(
                """
                INSERT INTO alert_dedup (
                    fingerprint, alert_id, service_name, environment,
                    first_seen_at, last_seen_at, occurrence_count, metadata
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (fingerprint) DO UPDATE SET
                    last_seen_at = EXCLUDED.last_seen_at,
                    occurrence_count = alert_dedup.occurrence_count + 1
                """,
                (
                    fingerprint,
                    f"ALERT-{i+1:05d}",
                    service,
                    random.choice(self.environments),
                    now - timedelta(days=random.randint(0, 7)),
                    now,
                    random.randint(1, 10),
                    json.dumps({
                        "error_pattern": random.choice(self.error_templates).format(service=service)
                    })
                )
            )
        
        logger.info(f"✓ Seeded {count} alert dedup records")
    
    async def run(self):
        """Run all seeding operations."""
        try:
            await self.connect()
            
            # Seed data in order (respecting foreign key constraints)
            await self.seed_audit_events(50)
            await self.seed_workflows(20)
            await self.seed_incidents(30)
            await self.seed_checkpoints(10)
            await self.seed_sla_metrics()
            await self.seed_llm_usage(100)
            await self.seed_alert_dedup(20)
            
            await self.conn.commit()
            
            logger.info("========================================")
            logger.info("✓ Database seeding completed successfully!")
            logger.info("========================================")
            
            # Print summary
            result = await self.conn.execute("""
                SELECT 
                    (SELECT COUNT(*) FROM audit_events) as audit_events,
                    (SELECT COUNT(*) FROM workflows) as workflows,
                    (SELECT COUNT(*) FROM incidents) as incidents,
                    (SELECT COUNT(*) FROM checkpoints) as checkpoints,
                    (SELECT COUNT(*) FROM service_sla_metrics) as sla_metrics,
                    (SELECT COUNT(*) FROM llm_usage) as llm_usage,
                    (SELECT COUNT(*) FROM alert_dedup) as alert_dedup
            """)
            counts = await result.fetchone()
            
            if counts:
                print("\nData Counts:")
                for key, value in counts.items():
                    print(f"  {key}: {value}")
            
        except Exception as e:
            logger.error(f"Seeding failed: {e}")
            if self.conn:
                await self.conn.rollback()
            raise
        finally:
            await self.close()

async def main():
    """Main entry point."""
    # Check if we should skip confirmation
    if "--force" in sys.argv or "-f" in sys.argv:
        proceed = True
    else:
        print("This will seed the database with sample data.")
        print("Make sure you have a development or test database configured.")
        response = input("Continue? (y/N): ")
        proceed = response.lower() == 'y'
    
    if not proceed:
        print("Seeding cancelled.")
        return
    
    seeder = DataSeeder()
    await seeder.run()

if __name__ == "__main__":
    asyncio.run(main())