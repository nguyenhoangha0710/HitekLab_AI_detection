CREATE TABLE IF NOT EXISTS ai_event (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    alert_id uuid,
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

CREATE TABLE IF NOT EXISTS alert (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    dedup_key varchar(500) NOT NULL,
    camera_id uuid NOT NULL REFERENCES camera(id) ON DELETE CASCADE,
    zone_id uuid REFERENCES zone(id) ON DELETE SET NULL,
    rule_config_id uuid REFERENCES rule_config(id) ON DELETE SET NULL,
    rule_type varchar(100) NOT NULL,
    object_type varchar(100),
    risk_level varchar(50) NOT NULL DEFAULT 'medium',
    lifecycle_status varchar(50) NOT NULL DEFAULT 'active',
    active_source_count integer NOT NULL DEFAULT 1,
    first_sequence_number integer,
    last_sequence_number integer,
    started_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    ended_at timestamptz,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE ai_event
    ADD COLUMN IF NOT EXISTS alert_id uuid;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_ai_event_alert_id'
    ) THEN
        ALTER TABLE ai_event
            ADD CONSTRAINT fk_ai_event_alert_id
            FOREIGN KEY (alert_id) REFERENCES alert(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS evidence (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    alert_id uuid REFERENCES alert(id) ON DELETE CASCADE,
    ai_event_id uuid NOT NULL REFERENCES ai_event(id) ON DELETE CASCADE,
    camera_id uuid NOT NULL REFERENCES camera(id) ON DELETE CASCADE,
    evidence_type varchar(50) NOT NULL,
    storage_key text NOT NULL,
    mime_type varchar(100) NOT NULL,
    file_size bigint,
    frame_id varchar(255),
    sequence_number integer,
    captured_at timestamptz NOT NULL,
    started_at timestamptz,
    ended_at timestamptz,
    duration_seconds double precision,
    codec varchar(50),
    fps double precision,
    frame_width integer,
    frame_height integer,
    status varchar(50),
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE evidence
    ADD COLUMN IF NOT EXISTS alert_id uuid;
ALTER TABLE evidence
    ADD COLUMN IF NOT EXISTS started_at timestamptz;
ALTER TABLE evidence
    ADD COLUMN IF NOT EXISTS ended_at timestamptz;
ALTER TABLE evidence
    ADD COLUMN IF NOT EXISTS duration_seconds double precision;
ALTER TABLE evidence
    ADD COLUMN IF NOT EXISTS codec varchar(50);
ALTER TABLE evidence
    ADD COLUMN IF NOT EXISTS fps double precision;
ALTER TABLE evidence
    ADD COLUMN IF NOT EXISTS frame_width integer;
ALTER TABLE evidence
    ADD COLUMN IF NOT EXISTS frame_height integer;
ALTER TABLE evidence
    ADD COLUMN IF NOT EXISTS status varchar(50);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_evidence_alert_id'
    ) THEN
        ALTER TABLE evidence
            ADD CONSTRAINT fk_evidence_alert_id
            FOREIGN KEY (alert_id) REFERENCES alert(id) ON DELETE CASCADE;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_ai_event_tenant_id ON ai_event(tenant_id);
CREATE INDEX IF NOT EXISTS idx_ai_event_alert_id ON ai_event(alert_id);
CREATE INDEX IF NOT EXISTS idx_ai_event_camera_id ON ai_event(camera_id);
CREATE INDEX IF NOT EXISTS idx_ai_event_zone_id ON ai_event(zone_id);
CREATE INDEX IF NOT EXISTS idx_ai_event_started_at ON ai_event(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_alert_tenant_id ON alert(tenant_id);
CREATE INDEX IF NOT EXISTS idx_alert_dedup_key ON alert(dedup_key);
CREATE INDEX IF NOT EXISTS idx_alert_camera_id ON alert(camera_id);
CREATE INDEX IF NOT EXISTS idx_alert_last_seen_at ON alert(last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_evidence_alert_id ON evidence(alert_id);
CREATE INDEX IF NOT EXISTS idx_evidence_ai_event_id ON evidence(ai_event_id);
CREATE INDEX IF NOT EXISTS idx_evidence_camera_id ON evidence(camera_id);
CREATE INDEX IF NOT EXISTS idx_evidence_captured_at ON evidence(captured_at DESC);

DROP TRIGGER IF EXISTS trg_ai_event_updated_at ON ai_event;
CREATE TRIGGER trg_ai_event_updated_at
BEFORE UPDATE ON ai_event
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_alert_updated_at ON alert;
CREATE TRIGGER trg_alert_updated_at
BEFORE UPDATE ON alert
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
