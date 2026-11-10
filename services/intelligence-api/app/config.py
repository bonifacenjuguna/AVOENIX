"""Environment-driven settings. No secret has a default value that would work in production."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _csv(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
    environment: str = "development"                       # development | production
    database_url: str | None = None                        # None -> in-memory backend (development only, data lost on restart)
    cors_origins: list[str] = field(default_factory=list)
    admin_email: str | None = None
    admin_password: str | None = None                      # bootstrap only; hashed immediately, never stored in clear
    session_ttl_hours: int = 12
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    rate_limit_per_minute: int = 60
    login_rate_limit_per_minute: int = 10
    max_body_bytes: int = 64_000
    project_id: str = "studio"
    cookie_secure: bool = True
    min_password_length: int = 12

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Settings":
        e = os.environ if env is None else env
        environment = e.get("AVOENIX_ENV", "development")
        return cls(
            environment=environment, database_url=e.get("DATABASE_URL") or None, cors_origins=_csv(e.get("AVOENIX_CORS_ORIGINS")),
            admin_email=e.get("AVOENIX_ADMIN_EMAIL") or None, admin_password=e.get("AVOENIX_ADMIN_PASSWORD") or None,
            session_ttl_hours=int(e.get("AVOENIX_SESSION_TTL_HOURS", "12")), max_failed_logins=int(e.get("AVOENIX_MAX_FAILED_LOGINS", "5")),
            lockout_minutes=int(e.get("AVOENIX_LOCKOUT_MINUTES", "15")), rate_limit_per_minute=int(e.get("AVOENIX_RATE_LIMIT_PER_MINUTE", "60")),
            login_rate_limit_per_minute=int(e.get("AVOENIX_LOGIN_RATE_LIMIT_PER_MINUTE", "10")),
            max_body_bytes=int(e.get("AVOENIX_MAX_BODY_BYTES", "64000")), project_id=e.get("AVOENIX_PROJECT_ID", "studio"),
            cookie_secure=e.get("AVOENIX_COOKIE_SECURE", "true" if environment == "production" else "false").lower() == "true",
        )

    def problems(self) -> list[str]:
        """Configuration errors that must stop startup in production."""
        out = []
        if self.environment == "production":
            if not self.database_url:
                out.append("DATABASE_URL is required in production (the in-memory backend loses all data)")
            if not self.cors_origins:
                out.append("AVOENIX_CORS_ORIGINS must list the Studio origin(s) in production")
            if "*" in self.cors_origins:
                out.append("AVOENIX_CORS_ORIGINS must not contain '*' (credentials are used)")
        if self.admin_password is not None and len(self.admin_password) < self.min_password_length:
            out.append(f"AVOENIX_ADMIN_PASSWORD must be at least {self.min_password_length} characters")
        return out
