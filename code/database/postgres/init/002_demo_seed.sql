WITH demo_tenant AS (
    INSERT INTO tenant (id, name, code, status)
    VALUES (
        '00000000-0000-4000-8000-000000000001',
        'Demo Tenant',
        'demo-tenant',
        'active'
    )
    ON CONFLICT (code) DO UPDATE
    SET name = excluded.name,
        status = excluded.status
    RETURNING id
),
demo_admin AS (
    INSERT INTO app_user (id, email, full_name, status)
    VALUES (
        '00000000-0000-4000-8000-000000000101',
        'admin@demo.local',
        'Demo Admin',
        'active'
    )
    ON CONFLICT (email) DO UPDATE
    SET full_name = excluded.full_name,
        status = excluded.status
    RETURNING id
),
demo_member AS (
    INSERT INTO tenant_member (id, tenant_id, user_id, role, status)
    SELECT
        '00000000-0000-4000-8000-000000000201',
        demo_tenant.id,
        demo_admin.id,
        'admin',
        'active'
    FROM demo_tenant, demo_admin
    ON CONFLICT (tenant_id, user_id) DO UPDATE
    SET role = excluded.role,
        status = excluded.status
    RETURNING id, tenant_id
),
warehouse AS (
    INSERT INTO location (id, tenant_id, name, code, status)
    SELECT
        '550e8400-e29b-41d4-a716-446655440101',
        demo_member.tenant_id,
        'Warehouse',
        'warehouse',
        'active'
    FROM demo_member
    ON CONFLICT (tenant_id, code) DO UPDATE
    SET name = excluded.name,
        status = excluded.status
    RETURNING id, tenant_id
),
main_gate AS (
    INSERT INTO location (id, tenant_id, name, code, status)
    SELECT
        '550e8400-e29b-41d4-a716-446655440102',
        demo_member.tenant_id,
        'Main Gate',
        'main-gate',
        'active'
    FROM demo_member
    ON CONFLICT (tenant_id, code) DO UPDATE
    SET name = excluded.name,
        status = excluded.status
    RETURNING id, tenant_id
),
warehouse_access AS (
    INSERT INTO user_location_access (tenant_id, tenant_member_id, location_id, permission_level)
    SELECT demo_member.tenant_id, demo_member.id, warehouse.id, 'admin'
    FROM demo_member, warehouse
    ON CONFLICT (tenant_member_id, location_id) DO UPDATE
    SET permission_level = excluded.permission_level
    RETURNING id
),
main_gate_access AS (
    INSERT INTO user_location_access (tenant_id, tenant_member_id, location_id, permission_level)
    SELECT demo_member.tenant_id, demo_member.id, main_gate.id, 'admin'
    FROM demo_member, main_gate
    ON CONFLICT (tenant_member_id, location_id) DO UPDATE
    SET permission_level = excluded.permission_level
    RETURNING id
),
camera_warehouse AS (
    INSERT INTO camera (id, tenant_id, location_id, name, source_type, source_url, status)
    SELECT
        '550e8400-e29b-41d4-a716-446655440001',
        warehouse.tenant_id,
        warehouse.id,
        'Camera 01 - Warehouse',
        'RTSP',
        'rtsp://mediamtx:8554/camera1',
        'active'
    FROM warehouse
    ON CONFLICT (tenant_id, source_url) DO UPDATE
    SET location_id = excluded.location_id,
        name = excluded.name,
        source_type = excluded.source_type,
        status = excluded.status
    RETURNING id
)
INSERT INTO camera (id, tenant_id, location_id, name, source_type, source_url, status)
SELECT
    '550e8400-e29b-41d4-a716-446655440002',
    main_gate.tenant_id,
    main_gate.id,
    'Camera 02 - Main Gate',
    'RTSP',
    'rtsp://mediamtx:8554/camera2',
    'active'
FROM main_gate
ON CONFLICT (tenant_id, source_url) DO UPDATE
SET location_id = excluded.location_id,
    name = excluded.name,
    source_type = excluded.source_type,
    status = excluded.status;
