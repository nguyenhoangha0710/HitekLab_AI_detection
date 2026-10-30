"""Phan quyen theo tenant + location cho Zone Service.

Mo hinh (bang da co trong 001_base_schema.sql):
    tenant_member.role          : owner | admin | operator | viewer   (vai tro trong tenant)
    user_location_access.level  : admin | operator | viewer           (quyen tai tung location)

Quy tac:
    - owner/admin cua tenant  -> admin tai MOI location cua tenant.
    - operator/viewer         -> chi cac location duoc gan trong user_location_access,
                                 voi muc permission_level cua tung location.
    - Moi du lieu (camera, zone, rule, ai_event, evidence, alert) quy ve camera.location_id.
    - Khong co quyen -> 404 (khong lo du lieu co ton tai); co quyen xem nhung thieu muc -> 403.
    - Service noi bo (AI Service, Edge Gateway) dung header X-Service-Key -> toan quyen.
    - AUTH_MODE=off -> toan quyen (giu hanh vi cu khi dev).

Danh sach location duoc tra lai moi request (cache ngan) chu khong nam trong token,
de admin rut/giao quyen co hieu luc ngay ma khong can cap lai token.
"""

import hmac
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import jwt_utils
from .config import ZoneServiceSettings
from .database import Database

LEVELS = {"viewer": 1, "operator": 2, "admin": 3}
TENANT_WIDE_ROLES = {"owner", "admin"}


class AuthError(Exception):
    """401: thieu token / token sai."""


class AccessDenied(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class Principal:
    kind: str  # "user" | "service" | "anonymous"
    subject: str
    tenant_id: Optional[str] = None
    tenant_member_id: Optional[str] = None
    role: Optional[str] = None
    email: Optional[str] = None
    full_name: Optional[str] = None
    # None = moi location (service / auth off / tenant admin); dict location_id -> level
    locations: Optional[Dict[str, str]] = field(default=None)

    @property
    def is_unrestricted(self) -> bool:
        return self.locations is None

    def level_for(self, location_id: str) -> Optional[str]:
        if self.locations is None:
            return "admin"
        return self.locations.get(str(location_id))

    def allowed_location_ids(self) -> Optional[List[str]]:
        return None if self.locations is None else sorted(self.locations.keys())


class AccessControl:
    def __init__(self, database: Database, settings: ZoneServiceSettings, clock=time.time) -> None:
        self.database = database
        self.settings = settings
        self._clock = clock
        self._cache: Dict[Tuple[str, str], Tuple[float, Principal]] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.settings.auth_mode == "jwt"

    # ------------------------------------------------------------ xac thuc
    def authenticate(self, authorization: Optional[str], access_token: Optional[str], service_key: Optional[str]) -> Principal:
        if service_key and self.settings.service_api_key and hmac.compare_digest(service_key, self.settings.service_api_key):
            return Principal(kind="service", subject="internal-service")
        if not self.enabled:
            return Principal(kind="anonymous", subject="auth-disabled")

        token = None
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        elif access_token:
            # <img>, <video>, EventSource khong gui duoc header -> cho phep ?access_token=
            token = access_token
        if not token:
            raise AuthError("Missing bearer token")
        try:
            claims = jwt_utils.decode(
                token,
                algorithm=self.settings.jwt_algorithm,
                secret=self.settings.jwt_secret,
                public_key=self.settings.jwt_public_key,
                issuer=self.settings.jwt_issuer,
                audience=self.settings.jwt_audience,
                now=self._clock(),
            )
        except jwt_utils.JwtError as exc:
            raise AuthError(str(exc)) from exc

        subject = claims.get(self.settings.jwt_user_claim)
        tenant = claims.get(self.settings.jwt_tenant_claim)
        if not subject or not tenant:
            raise AuthError("Token is missing user or tenant claim")
        return self._load_user(str(subject), str(tenant))

    def _load_user(self, subject: str, tenant: str) -> Principal:
        key = (subject, tenant)
        now = self._clock()
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] > now:
                return cached[1]
        with self.database.session() as connection:
            principal = self._query_user(connection, subject, tenant)
        with self._lock:
            self._cache[key] = (now + self.settings.access_cache_seconds, principal)
        return principal

    def invalidate_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    def _query_user(self, connection, subject: str, tenant: str) -> Principal:
        # tenant claim co the la id (uuid) hoac code ("demo-tenant").
        member = self.database.fetchone(
            connection,
            """
            SELECT tm.id AS member_id, tm.role AS role, tm.tenant_id AS tenant_id,
                   u.id AS user_id, u.email AS email, u.full_name AS full_name
            FROM tenant_member tm
            JOIN app_user u ON u.id = tm.user_id
            JOIN tenant t ON t.id = tm.tenant_id
            WHERE (CAST(u.id AS TEXT) = ? OR u.email = ?)
              AND (CAST(t.id AS TEXT) = ? OR t.code = ?)
              AND CAST(tm.status AS TEXT) = 'active'
              AND CAST(u.status AS TEXT) = 'active'
            """,
            (subject, subject, tenant, tenant),
        )
        if member is None:
            raise AuthError("User is not an active member of this tenant")

        role = str(member["role"])
        tenant_id = str(member["tenant_id"])
        if role in TENANT_WIDE_ROLES:
            rows = self.database.fetchall(connection, "SELECT id FROM location WHERE tenant_id = ?", (tenant_id,))
            locations = {str(row["id"]): "admin" for row in rows}
        else:
            rows = self.database.fetchall(
                connection,
                """
                SELECT ula.location_id AS location_id, ula.permission_level AS level
                FROM user_location_access ula
                JOIN location l ON l.id = ula.location_id
                WHERE ula.tenant_member_id = ? AND l.tenant_id = ?
                """,
                (member["member_id"], tenant_id),
            )
            locations = {str(row["location_id"]): str(row["level"]) for row in rows}
        return Principal(
            kind="user",
            subject=str(member["user_id"]),
            tenant_id=tenant_id,
            tenant_member_id=str(member["member_id"]),
            role=role,
            email=member["email"],
            full_name=member["full_name"],
            locations=locations,
        )

    # ------------------------------------------------------------ phan quyen
    def require_location(self, principal: Principal, location_id: Optional[str], min_level: str = "viewer") -> None:
        if principal.is_unrestricted:
            return
        level = principal.level_for(str(location_id)) if location_id else None
        if level is None:
            raise AccessDenied(404, "Not found")
        if LEVELS.get(level, 0) < LEVELS[min_level]:
            raise AccessDenied(403, "Requires '{}' permission on this location".format(min_level))

    def require_camera(self, principal: Principal, connection, camera_id: str, min_level: str = "viewer"):
        camera = self.database.fetchone(connection, "SELECT * FROM camera WHERE id = ?", (camera_id,))
        if camera is None:
            raise AccessDenied(404, "Camera not found")
        if principal.kind == "user" and str(camera["tenant_id"]) != principal.tenant_id:
            raise AccessDenied(404, "Camera not found")
        self.require_location(principal, camera["location_id"], min_level)
        return camera

    def require_via(self, principal: Principal, connection, table: str, row_id: str, min_level: str = "viewer"):
        """Kiem tra quyen cho zone / ai_event / evidence / alert / camera_reference_frame qua camera_id."""
        if table not in {"zone", "ai_event", "evidence", "alert", "camera_reference_frame"}:
            raise ValueError(table)
        row = self.database.fetchone(connection, "SELECT * FROM {} WHERE id = ?".format(table), (row_id,))
        if row is None:
            raise AccessDenied(404, "Not found")
        self.require_camera(principal, connection, str(row["camera_id"]), min_level)
        return row

    def require_rule(self, principal: Principal, connection, rule_id: str, min_level: str = "viewer"):
        row = self.database.fetchone(connection, "SELECT * FROM rule_config WHERE id = ?", (rule_id,))
        if row is None:
            raise AccessDenied(404, "Rule not found")
        self.require_via(principal, connection, "zone", str(row["zone_id"]), min_level)
        return row

    def require_tenant_admin(self, principal: Principal) -> None:
        if principal.kind in ("service", "anonymous"):
            return
        if principal.role not in TENANT_WIDE_ROLES:
            raise AccessDenied(403, "Requires tenant owner/admin")

    def allowed_camera_ids(self, principal: Principal, connection) -> Optional[List[str]]:
        """None = khong gioi han. List (co the rong) = chi cac camera nay."""
        if principal.is_unrestricted:
            return None
        location_ids = principal.allowed_location_ids()
        if not location_ids:
            return []
        placeholders = ",".join("?" for _ in location_ids)
        rows = self.database.fetchall(
            connection,
            "SELECT id FROM camera WHERE tenant_id = ? AND location_id IN ({})".format(placeholders),
            (principal.tenant_id, *location_ids),
        )
        return [str(row["id"]) for row in rows]

    # ------------------------------------------------------------ dev login
    def issue_dev_token(self, email: str) -> str:
        if not (self.enabled and self.settings.auth_dev_login and self.settings.jwt_algorithm.upper() == "HS256"):
            raise AccessDenied(404, "Dev login is disabled")
        with self.database.session() as connection:
            row = self.database.fetchone(
                connection,
                """
                SELECT u.id AS user_id, t.id AS tenant_id, tm.role AS role
                FROM app_user u
                JOIN tenant_member tm ON tm.user_id = u.id
                JOIN tenant t ON t.id = tm.tenant_id
                WHERE u.email = ? AND CAST(tm.status AS TEXT) = 'active' AND CAST(u.status AS TEXT) = 'active'
                """,
                (email,),
            )
        if row is None:
            raise AccessDenied(404, "Unknown demo user")
        now = int(self._clock())
        claims = {
            self.settings.jwt_user_claim: str(row["user_id"]),
            self.settings.jwt_tenant_claim: str(row["tenant_id"]),
            "role": str(row["role"]),
            "iat": now,
            "exp": now + 12 * 3600,
        }
        if self.settings.jwt_issuer:
            claims["iss"] = self.settings.jwt_issuer
        if self.settings.jwt_audience:
            claims["aud"] = self.settings.jwt_audience
        return jwt_utils.encode_hs256(claims, self.settings.jwt_secret or "")

    def dev_users(self) -> List[dict]:
        if not (self.enabled and self.settings.auth_dev_login):
            return []
        with self.database.session() as connection:
            rows = self.database.fetchall(
                connection,
                """
                SELECT u.email AS email, u.full_name AS full_name, tm.role AS role
                FROM app_user u JOIN tenant_member tm ON tm.user_id = u.id
                WHERE CAST(tm.status AS TEXT) = 'active' AND CAST(u.status AS TEXT) = 'active'
                ORDER BY u.email
                """,
                (),
            )
        return [{"email": r["email"], "full_name": r["full_name"], "role": str(r["role"])} for r in rows]
