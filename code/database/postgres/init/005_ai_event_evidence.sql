CREATE TABLE IF NOT EXISTS ai_event (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    source_event_id varchar(255) NOT NULL UNIQUE,
    camera_id uuid NOT NULL REFERENCES camera(id) ON DELETE CASCADE,
    zone_id uuid REFERENCES zone(id) ON DELETE SET NULL,
    rule_config_id uuid REFERENCES rule_config(id) ON DELETE SET NULL,
    event_type varchar(100) NOT NULL,
    object_type varchar(100),
    track_id varchar(100),
    confidence double precision CHECK (
        confidence IS NULL OR (confidence >= 0 AND confidence <= 1)
    ),
    lifecycle_status varchar(50) NOT NULL DEFAULT 'active',
    first_sequence_number integer,
    last_sequence_number integer,
    started_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    ended_at timestamptz,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS evidence (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    ai_event_id uuid NOT NULL REFERENCES ai_event(id) ON DELETE CASCADE,
    camera_id uuid NOT NULL REFERENCES camera(id) ON DELETE CASCADE,
    evidence_type varchar(50) NOT NULL,
    storage_key text NOT NULL,
    mime_type varchar(100) NOT NULL,
    file_size bigint,
    frame_id varchar(255),
    sequence_number integer,
    captured_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ai_event_tenant_id ON ai_event(tenant_id);
CREATE INDEX IF NOT EXISTS idx_ai_event_camera_id ON ai_event(camera_id);
CREATE INDEX IF NOT EXISTS idx_ai_event_zone_id ON ai_event(zone_id);
CREATE INDEX IF NOT EXISTS idx_ai_event_started_at ON ai_event(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_evidence_ai_event_id ON evidence(ai_event_id);
CREATE INDEX IF NOT EXISTS idx_evidence_camera_id ON evidence(camera_id);
CREATE INDEX IF NOT EXISTS idx_evidence_captured_at ON evidence(captured_at DESC);

DROP TRIGGER IF EXISTS trg_ai_event_updated_at ON ai_event;
CREATE TRIGGER trg_ai_event_updated_at
BEFORE UPDATE ON ai_event
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
