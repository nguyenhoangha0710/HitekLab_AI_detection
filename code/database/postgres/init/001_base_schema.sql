CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tenant_status') THEN
        CREATE TYPE tenant_status AS ENUM ('active', 'disabled');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_status') THEN
        CREATE TYPE user_status AS ENUM ('active', 'disabled');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'member_role') THEN
        CREATE TYPE member_role AS ENUM ('owner', 'admin', 'operator', 'viewer');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'member_status') THEN
        CREATE TYPE member_status AS ENUM ('active', 'disabled');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'access_level') THEN
        CREATE TYPE access_level AS ENUM ('admin', 'operator', 'viewer');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'location_status') THEN
        CREATE TYPE location_status AS ENUM ('active', 'disabled');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'camera_status') THEN
        CREATE TYPE camera_status AS ENUM ('active', 'inactive', 'offline', 'disabled');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS tenant (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name varchar(255) NOT NULL,
    code varchar(100) NOT NULL UNIQUE,
    status tenant_status NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app_user (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email varchar(255) NOT NULL UNIQUE,
    full_name varchar(255) NOT NULL,
    password_hash text,
    status user_status NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tenant_member (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    role member_role NOT NULL DEFAULT 'viewer',
    status member_status NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, user_id),
    UNIQUE (id, tenant_id)
);

CREATE TABLE IF NOT EXISTS location (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    name varchar(255) NOT NULL,
    code varchar(100) NOT NULL,
    status location_status NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, code),
    UNIQUE (id, tenant_id)
);

CREATE TABLE IF NOT EXISTS user_location_access (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    tenant_member_id uuid NOT NULL,
    location_id uuid NOT NULL,
    permission_level access_level NOT NULL DEFAULT 'viewer',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_member_id, location_id),
    FOREIGN KEY (tenant_member_id, tenant_id) REFERENCES tenant_member(id, tenant_id) ON DELETE CASCADE,
    FOREIGN KEY (location_id, tenant_id) REFERENCES location(id, tenant_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS camera (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    location_id uuid NOT NULL,
    name varchar(255) NOT NULL,
    source_type varchar(50) NOT NULL,
    source_url text NOT NULL,
    status camera_status NOT NULL DEFAULT 'active',
    last_seen_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (location_id, name),
    UNIQUE (tenant_id, source_url),
    UNIQUE (id, tenant_id),
    FOREIGN KEY (location_id, tenant_id) REFERENCES location(id, tenant_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS camera_reference_frame (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    camera_id uuid NOT NULL REFERENCES camera(id) ON DELETE CASCADE,
    storage_key text NOT NULL,
    mime_type varchar(100) NOT NULL,
    frame_width integer NOT NULL CHECK (frame_width > 0),
    frame_height integer NOT NULL CHECK (frame_height > 0),
    captured_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS zone (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    camera_id uuid NOT NULL,
    name varchar(255) NOT NULL,
    zone_type varchar(100) NOT NULL,
    polygon jsonb NOT NULL,
    frame_width integer NOT NULL CHECK (frame_width > 0),
    frame_height integer NOT NULL CHECK (frame_height > 0),
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (camera_id, name),
    UNIQUE (id, tenant_id),
    FOREIGN KEY (camera_id, tenant_id) REFERENCES camera(id, tenant_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS rule_config (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    zone_id uuid NOT NULL,
    rule_type varchar(100) NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    object_type varchar(100),
    duration_threshold integer CHECK (duration_threshold IS NULL OR duration_threshold >= 0),
    people_threshold integer CHECK (people_threshold IS NULL OR people_threshold >= 0),
    confidence_threshold double precision CHECK (
        confidence_threshold IS NULL OR (confidence_threshold >= 0 AND confidence_threshold <= 1)
    ),
    use_active_time boolean NOT NULL DEFAULT false,
    active_start_time time,
    active_end_time time,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (zone_id, rule_type),
    FOREIGN KEY (zone_id, tenant_id) REFERENCES zone(id, tenant_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ai_event (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    alert_id uuid,
    source_event_id varchar(255) NOT NULL UNIQUE,
    camera_id uuid NOT NULL,
    zone_id uuid,
    rule_config_id uuid,
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
    updated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (camera_id) REFERENCES camera(id) ON DELETE CASCADE,
    FOREIGN KEY (zone_id) REFERENCES zone(id) ON DELETE SET NULL,
    FOREIGN KEY (rule_config_id) REFERENCES rule_config(id) ON DELETE SET NULL
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

CREATE INDEX IF NOT EXISTS idx_tenant_member_tenant_id ON tenant_member(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tenant_member_user_id ON tenant_member(user_id);
CREATE INDEX IF NOT EXISTS idx_location_tenant_id ON location(tenant_id);
CREATE INDEX IF NOT EXISTS idx_user_location_access_tenant_id ON user_location_access(tenant_id);
CREATE INDEX IF NOT EXISTS idx_user_location_access_member_id ON user_location_access(tenant_member_id);
CREATE INDEX IF NOT EXISTS idx_user_location_access_location_id ON user_location_access(location_id);
CREATE INDEX IF NOT EXISTS idx_camera_tenant_id ON camera(tenant_id);
CREATE INDEX IF NOT EXISTS idx_camera_location_id ON camera(location_id);
CREATE INDEX IF NOT EXISTS idx_reference_frame_camera_id ON camera_reference_frame(camera_id);
CREATE INDEX IF NOT EXISTS idx_zone_tenant_id ON zone(tenant_id);
CREATE INDEX IF NOT EXISTS idx_zone_camera_id ON zone(camera_id);
CREATE INDEX IF NOT EXISTS idx_rule_config_tenant_id ON rule_config(tenant_id);
CREATE INDEX IF NOT EXISTS idx_rule_config_zone_id ON rule_config(zone_id);
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

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tenant_updated_at ON tenant;
CREATE TRIGGER trg_tenant_updated_at
BEFORE UPDATE ON tenant
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_app_user_updated_at ON app_user;
CREATE TRIGGER trg_app_user_updated_at
BEFORE UPDATE ON app_user
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tenant_member_updated_at ON tenant_member;
CREATE TRIGGER trg_tenant_member_updated_at
BEFORE UPDATE ON tenant_member
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_location_updated_at ON location;
CREATE TRIGGER trg_location_updated_at
BEFORE UPDATE ON location
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_user_location_access_updated_at ON user_location_access;
CREATE TRIGGER trg_user_location_access_updated_at
BEFORE UPDATE ON user_location_access
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_camera_updated_at ON camera;
CREATE TRIGGER trg_camera_updated_at
BEFORE UPDATE ON camera
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_zone_updated_at ON zone;
CREATE TRIGGER trg_zone_updated_at
BEFORE UPDATE ON zone
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_rule_config_updated_at ON rule_config;
CREATE TRIGGER trg_rule_config_updated_at
BEFORE UPDATE ON rule_config
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_ai_event_updated_at ON ai_event;
CREATE TRIGGER trg_ai_event_updated_at
BEFORE UPDATE ON ai_event
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_alert_updated_at ON alert;
CREATE TRIGGER trg_alert_updated_at
BEFORE UPDATE ON alert
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
