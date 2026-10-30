-- User demo de thu phan quyen theo location (chay lai nhieu lan van an toan).
--   owner@demo.local          owner    -> thay ca 2 location
--   admin@demo.local          admin    -> thay ca 2 location (tao o 002_demo_seed.sql)
--   kho.operator@demo.local   operator -> chi Warehouse (operator: xem + xu ly canh bao)
--   cong.viewer@demo.local    viewer   -> chi Main Gate (chi xem)
-- Chi cap nhat role/permission cua cac user demo nay, khong dong vao user that.

INSERT INTO app_user (id, email, full_name, status) VALUES
    ('00000000-0000-4000-8000-000000000102', 'owner@demo.local', 'Demo Owner', 'active'),
    ('00000000-0000-4000-8000-000000000103', 'kho.operator@demo.local', 'Van hanh Kho', 'active'),
    ('00000000-0000-4000-8000-000000000104', 'cong.viewer@demo.local', 'Bao ve Cong', 'active')
ON CONFLICT (email) DO NOTHING;

INSERT INTO tenant_member (id, tenant_id, user_id, role, status)
SELECT v.id::uuid, t.id, u.id, v.role::member_role, 'active'
FROM (VALUES
    ('00000000-0000-4000-8000-000000000202', 'owner@demo.local', 'owner'),
    ('00000000-0000-4000-8000-000000000203', 'kho.operator@demo.local', 'operator'),
    ('00000000-0000-4000-8000-000000000204', 'cong.viewer@demo.local', 'viewer')
) AS v(id, email, role)
JOIN app_user u ON u.email = v.email
JOIN tenant t ON t.code = 'demo-tenant'
ON CONFLICT (tenant_id, user_id) DO NOTHING;

INSERT INTO user_location_access (tenant_id, tenant_member_id, location_id, permission_level)
SELECT tm.tenant_id, tm.id, l.id, v.level::access_level
FROM (VALUES
    ('kho.operator@demo.local', 'warehouse', 'operator'),
    ('cong.viewer@demo.local', 'main-gate', 'viewer')
) AS v(email, location_code, level)
JOIN app_user u ON u.email = v.email
JOIN tenant t ON t.code = 'demo-tenant'
JOIN tenant_member tm ON tm.user_id = u.id AND tm.tenant_id = t.id
JOIN location l ON l.tenant_id = t.id AND l.code = v.location_code
ON CONFLICT (tenant_member_id, location_id) DO NOTHING;
