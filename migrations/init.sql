-- migrations/init.sql
-- Auto-SRE-Graph Database Initialization
-- PostgreSQL 15+ Required

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "citext";

-- ============================================
-- 1. LangGraph Checkpoint Tables
-- These are managed by AsyncPostgresSaver.setup() at runtime.
-- We only create the migrations tracking table here so init is clean.
-- ============================================

CREATE TABLE IF NOT EXISTS checkpoint_migrations (
    v INTEGER PRIMARY KEY
);

-- ============================================
-- 2. Audit & Compliance Tables
-- ============================================

-- Audit events table for compliance logging
CREATE TABLE IF NOT EXISTS audit_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id TEXT NOT NULL UNIQUE,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    target TEXT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    environment TEXT NOT NULL,
    source_ip TEXT,
    details JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_events_action ON audit_events(action);
CREATE INDEX IF NOT EXISTS idx_audit_events_actor ON audit_events(actor);
CREATE INDEX IF NOT EXISTS idx_audit_events_target ON audit_events(target);
CREATE INDEX IF NOT EXISTS idx_audit_events_timestamp ON audit_events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_environment ON audit_events(environment);

-- Audit event count by day for reporting
CREATE MATERIALIZED VIEW IF NOT EXISTS audit_events_daily AS
SELECT 
    DATE(timestamp) as event_date,
    environment,
    action,
    COUNT(*) as event_count
FROM audit_events
GROUP BY DATE(timestamp), environment, action
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_events_daily ON audit_events_daily(event_date, environment, action);

-- ============================================
-- 3. Workflow & Incident Tables
-- ============================================

-- Workflow instances table
CREATE TABLE IF NOT EXISTS workflows (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    thread_id TEXT NOT NULL UNIQUE,
    alert_id TEXT NOT NULL,
    service_name TEXT NOT NULL,
    environment TEXT NOT NULL,
    status TEXT NOT NULL,
    jira_ticket_id TEXT,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'::jsonb,
    error_count INTEGER DEFAULT 0,
    error_messages TEXT[]
);

CREATE INDEX IF NOT EXISTS idx_workflows_thread_id ON workflows(thread_id);
CREATE INDEX IF NOT EXISTS idx_workflows_alert_id ON workflows(alert_id);
CREATE INDEX IF NOT EXISTS idx_workflows_service_name ON workflows(service_name);
CREATE INDEX IF NOT EXISTS idx_workflows_status ON workflows(status);
CREATE INDEX IF NOT EXISTS idx_workflows_environment ON workflows(environment);
CREATE INDEX IF NOT EXISTS idx_workflows_started_at ON workflows(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_workflows_completed_at ON workflows(completed_at DESC);

-- Workflow events table
CREATE TABLE IF NOT EXISTS workflow_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workflow_id UUID REFERENCES workflows(id) ON DELETE CASCADE,
    thread_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    node_name TEXT,
    event_data JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_workflow_events_workflow_id ON workflow_events(workflow_id);
CREATE INDEX IF NOT EXISTS idx_workflow_events_thread_id ON workflow_events(thread_id);
CREATE INDEX IF NOT EXISTS idx_workflow_events_event_type ON workflow_events(event_type);
CREATE INDEX IF NOT EXISTS idx_workflow_events_created_at ON workflow_events(created_at DESC);

-- ============================================
-- 4. Incident & Resolution History
-- ============================================

-- Incidents table for historical tracking
CREATE TABLE IF NOT EXISTS incidents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_id TEXT NOT NULL UNIQUE,
    alert_id TEXT NOT NULL,
    service_name TEXT NOT NULL,
    environment TEXT NOT NULL,
    severity TEXT NOT NULL,
    error_message TEXT NOT NULL,
    stack_trace TEXT,
    root_cause_summary TEXT,
    confidence_score NUMERIC(5,4),
    proposed_action TEXT,
    remediation_script TEXT,
    resolution_time_seconds INTEGER,
    jira_ticket_id TEXT,
    status TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP WITH TIME ZONE,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_incidents_incident_id ON incidents(incident_id);
CREATE INDEX IF NOT EXISTS idx_incidents_alert_id ON incidents(alert_id);
CREATE INDEX IF NOT EXISTS idx_incidents_service_name ON incidents(service_name);
CREATE INDEX IF NOT EXISTS idx_incidents_severity ON incidents(severity);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);
CREATE INDEX IF NOT EXISTS idx_incidents_created_at ON incidents(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_incidents_resolved_at ON incidents(resolved_at DESC);

-- Incident metrics view
CREATE VIEW incident_metrics AS
SELECT 
    service_name,
    environment,
    DATE_TRUNC('hour', created_at) as hour,
    COUNT(*) as incident_count,
    AVG(confidence_score) as avg_confidence,
    COUNT(CASE WHEN status = 'RESOLVED' THEN 1 END) as resolved_count,
    AVG(resolution_time_seconds) as avg_resolution_time,
    MAX(resolution_time_seconds) as max_resolution_time,
    MIN(resolution_time_seconds) as min_resolution_time
FROM incidents
GROUP BY service_name, environment, DATE_TRUNC('hour', created_at);

-- ============================================
-- 5. Service Performance & SLA Tables
-- ============================================

-- Service SLA metrics
CREATE TABLE IF NOT EXISTS service_sla_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    service_name TEXT NOT NULL,
    environment TEXT NOT NULL,
    metric_date DATE NOT NULL,
    total_incidents INTEGER DEFAULT 0,
    resolved_incidents INTEGER DEFAULT 0,
    total_downtime_seconds INTEGER DEFAULT 0,
    avg_resolution_time_seconds INTEGER DEFAULT 0,
    p95_resolution_time_seconds INTEGER DEFAULT 0,
    p99_resolution_time_seconds INTEGER DEFAULT 0,
    rollback_count INTEGER DEFAULT 0,
    escalation_count INTEGER DEFAULT 0,
    success_rate NUMERIC(5,2) DEFAULT 100.0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(service_name, environment, metric_date)
);

CREATE INDEX IF NOT EXISTS idx_service_sla_service_name ON service_sla_metrics(service_name);
CREATE INDEX IF NOT EXISTS idx_service_sla_metric_date ON service_sla_metrics(metric_date DESC);

-- ============================================
-- 6. Cost Tracking
-- ============================================

-- LLM usage costs
CREATE TABLE IF NOT EXISTS llm_usage (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    cost NUMERIC(10,6) NOT NULL,
    environment TEXT NOT NULL,
    service_name TEXT,
    alert_id TEXT,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_llm_usage_request_id ON llm_usage(request_id);
CREATE INDEX IF NOT EXISTS idx_llm_usage_model ON llm_usage(model);
CREATE INDEX IF NOT EXISTS idx_llm_usage_timestamp ON llm_usage(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_llm_usage_environment ON llm_usage(environment);
CREATE INDEX IF NOT EXISTS idx_llm_usage_service_name ON llm_usage(service_name);

-- Monthly cost summary view
CREATE VIEW monthly_cost_summary AS
SELECT 
    DATE_TRUNC('month', timestamp) as month,
    environment,
    model,
    COUNT(*) as request_count,
    SUM(input_tokens) as total_input_tokens,
    SUM(output_tokens) as total_output_tokens,
    SUM(total_tokens) as total_tokens,
    SUM(cost) as total_cost
FROM llm_usage
GROUP BY DATE_TRUNC('month', timestamp), environment, model
ORDER BY month DESC, environment, model;

-- ============================================
-- 7. Caching & Deduplication
-- ============================================

-- Alert deduplication tracking
CREATE TABLE IF NOT EXISTS alert_dedup (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    fingerprint TEXT NOT NULL,
    alert_id TEXT NOT NULL,
    service_name TEXT NOT NULL,
    environment TEXT NOT NULL,
    first_seen_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    occurrence_count INTEGER DEFAULT 1,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_alert_dedup_fingerprint ON alert_dedup(fingerprint);
CREATE INDEX IF NOT EXISTS idx_alert_dedup_alert_id ON alert_dedup(alert_id);
CREATE INDEX IF NOT EXISTS idx_alert_dedup_service_name ON alert_dedup(service_name);
CREATE INDEX IF NOT EXISTS idx_alert_dedup_last_seen_at ON alert_dedup(last_seen_at DESC);

-- ============================================
-- 8. Embedding Cache
-- ============================================

-- Embedding cache for vector search optimization
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS embedding_cache (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    text_hash TEXT NOT NULL UNIQUE,
    text_preview TEXT,
    embedding_vector vector(1536),
    model TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_accessed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    access_count INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_embedding_cache_text_hash ON embedding_cache(text_hash);
CREATE INDEX IF NOT EXISTS idx_embedding_cache_last_accessed ON embedding_cache(last_accessed_at DESC);
CREATE INDEX IF NOT EXISTS idx_embedding_cache_access_count ON embedding_cache(access_count DESC);

-- ============================================
-- 9. Database Functions
-- ============================================

-- Function to update workflow timestamps
CREATE OR REPLACE FUNCTION update_workflow_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_workflows_timestamp
BEFORE UPDATE ON workflows
FOR EACH ROW
EXECUTE FUNCTION update_workflow_timestamp();

-- Function to update SLA metrics timestamp
CREATE OR REPLACE FUNCTION update_sla_metrics_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_service_sla_timestamp
BEFORE UPDATE ON service_sla_metrics
FOR EACH ROW
EXECUTE FUNCTION update_sla_metrics_timestamp();

-- Function to refresh daily audit view
CREATE OR REPLACE FUNCTION refresh_audit_events_daily()
RETURNS VOID AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY audit_events_daily;
END;
$$ LANGUAGE plpgsql;

-- ============================================
-- 10. Database Roles & Permissions
-- ============================================

-- Create application user if not exists
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_user WHERE usename = 'sre_app_user') THEN
        CREATE USER sre_app_user WITH PASSWORD 'change_me_in_production';
    END IF;
END
$$;

-- Grant permissions
GRANT CONNECT ON DATABASE sre_workflows TO sre_app_user;

-- Grant schema permissions
GRANT USAGE ON SCHEMA public TO sre_app_user;

-- Grant table permissions
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO sre_app_user;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO sre_app_user;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO sre_app_user;

-- Grant default permissions for future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sre_app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE ON SEQUENCES TO sre_app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO sre_app_user;

-- ============================================
-- 11. Comments
-- ============================================

COMMENT ON DATABASE sre_workflows IS 'Auto-SRE-Graph database for enterprise AI workflow automation';

COMMENT ON TABLE checkpoints IS 'LangGraph checkpoint storage for workflow state persistence';
COMMENT ON TABLE audit_events IS 'Audit log for compliance and security tracking';
COMMENT ON TABLE workflows IS 'Workflow instance tracking';
COMMENT ON TABLE incidents IS 'Incident and resolution history';
COMMENT ON TABLE service_sla_metrics IS 'Service-level agreement metrics per service';
COMMENT ON TABLE llm_usage IS 'LLM usage and cost tracking';
COMMENT ON TABLE alert_dedup IS 'Alert deduplication tracking';
COMMENT ON TABLE embedding_cache IS 'Cache for generated embeddings';

-- ============================================
-- 12. Initial Data (Optional)
-- ============================================

-- Insert sample service entries
INSERT INTO service_sla_metrics (service_name, environment, metric_date, total_incidents, resolved_incidents)
SELECT 
    service_name,
    'PROD',
    CURRENT_DATE,
    0,
    0
FROM (VALUES 
    ('auth-service', 'PROD'),
    ('payment-service', 'PROD'),
    ('order-service', 'PROD'),
    ('user-service', 'PROD'),
    ('notification-service', 'PROD')
) AS services(service_name, environment)
ON CONFLICT (service_name, environment, metric_date) DO NOTHING;