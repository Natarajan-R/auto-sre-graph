-- migrations/002_add_mining_tables.sql
-- Pattern Mining Engine - Persistent Cluster Storage
-- Phase 2: Production Hardening

-- ============================================
-- 1. Mining Clusters Table
-- Persists cluster assignments so results survive
-- across API restarts and enable trend analysis
-- ============================================

CREATE TABLE IF NOT EXISTS mining_clusters (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    cluster_id INTEGER NOT NULL,
    error_type TEXT NOT NULL,
    representative_error TEXT NOT NULL,
    size INTEGER NOT NULL,
    services TEXT[] NOT NULL DEFAULT '{}',
    severities TEXT[] NOT NULL DEFAULT '{}',
    first_seen TIMESTAMP WITH TIME ZONE,
    last_seen TIMESTAMP WITH TIME ZONE,
    is_noise BOOLEAN DEFAULT FALSE,
    snapshot_period TEXT NOT NULL,
    snapshot_start TIMESTAMP WITH TIME ZONE NOT NULL,
    snapshot_end TIMESTAMP WITH TIME ZONE NOT NULL,
    velocity REAL DEFAULT 0.0,
    trend TEXT DEFAULT 'stable',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(cluster_id, snapshot_period)
);

-- ============================================
-- 2. Mining Events Table
-- Individual error events linked to their cluster
-- ============================================

CREATE TABLE IF NOT EXISTS mining_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    cluster_ref_id UUID REFERENCES mining_clusters(id) ON DELETE CASCADE,
    thread_id TEXT,
    alert_id TEXT,
    timestamp TIMESTAMP WITH TIME ZONE,
    service_name TEXT NOT NULL,
    environment TEXT,
    error_message TEXT NOT NULL,
    severity TEXT DEFAULT 'HIGH',
    snapshot_period TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- 3. Indexes
-- ============================================

CREATE INDEX IF NOT EXISTS idx_mining_clusters_error_type ON mining_clusters(error_type);
CREATE INDEX IF NOT EXISTS idx_mining_clusters_snapshot ON mining_clusters(snapshot_period);
CREATE INDEX IF NOT EXISTS idx_mining_clusters_created_at ON mining_clusters(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_mining_clusters_velocity ON mining_clusters(velocity DESC);
CREATE INDEX IF NOT EXISTS idx_mining_clusters_trend ON mining_clusters(trend);
CREATE INDEX IF NOT EXISTS idx_mining_clusters_services ON mining_clusters USING GIN(services);
CREATE INDEX IF NOT EXISTS idx_mining_events_service ON mining_events(service_name);
CREATE INDEX IF NOT EXISTS idx_mining_events_timestamp ON mining_events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_mining_events_snapshot ON mining_events(snapshot_period);
CREATE INDEX IF NOT EXISTS idx_mining_events_cluster_ref ON mining_events(cluster_ref_id);

-- ============================================
-- 4. Comments
-- ============================================

COMMENT ON TABLE mining_clusters IS 'Persistent error cluster snapshots from pattern mining engine';
COMMENT ON TABLE mining_events IS 'Individual error events linked to their cluster snapshot';
COMMENT ON COLUMN mining_clusters.snapshot_period IS 'YYYYMMDDHH period identifier for the mining run';
COMMENT ON COLUMN mining_clusters.velocity IS 'Linear regression slope of daily occurrence counts';
COMMENT ON COLUMN mining_clusters.trend IS 'accelerating | declining | stable';
