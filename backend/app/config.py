"""Runtime settings, read once from environment variables."""
import os
import secrets
from functools import lru_cache
from pathlib import Path


class Settings:
    def __init__(self) -> None:
        self.data_dir = Path(os.getenv("XYBERAH_DATA_DIR", "/data"))
        self.static_dir = Path(os.getenv("XYBERAH_STATIC_DIR", "/opt/xyberah-app/static"))
        self.engine_dir = Path(os.getenv("XYBERAH_ENGINE_DIR", "/opt/xyberah-app/engine"))
        self.branding_file = Path(os.getenv("XYBERAH_BRANDING_FILE", "/config/branding.yaml"))
        self.certs_dir = Path(os.getenv("XYBERAH_CERTS_DIR", "/certs"))
        self.branding_locked = os.getenv("XYBERAH_BRANDING_LOCKED", "false").lower() == "true"

        # Promptfoo (Xyberah build) CLI and the two isolated tool environments
        self.engine_bin = os.getenv("XYBERAH_ENGINE_BIN", "xyberah")
        self.tools_dir = Path(os.getenv("XYBERAH_TOOLS_DIR", str(self.data_dir / "tools")))
        self.garak_python = self.tools_dir / "garak" / "bin" / "python"
        self.pyrit_python = self.tools_dir / "pyrit" / "bin" / "python"
        self.inspect_python = self.tools_dir / "inspect" / "bin" / "python"
        self.inspect_bin = self.tools_dir / "inspect" / "bin" / "inspect"
        self.modelaudit_python = self.tools_dir / "modelaudit" / "bin" / "python"
        self.modelaudit_bin = self.tools_dir / "modelaudit" / "bin" / "modelaudit"
        self.deepteam_python = self.tools_dir / "deepteam" / "bin" / "python"

        self.admin_username = os.getenv("XYBERAH_ADMIN_USERNAME", "admin")
        self.admin_password = os.getenv("XYBERAH_ADMIN_PASSWORD", "")
        self.cookie_secure = os.getenv("XYBERAH_COOKIE_SECURE", "false").lower() == "true"
        self.session_hours = int(os.getenv("XYBERAH_SESSION_HOURS", "12"))
        self.max_concurrent_campaigns = int(os.getenv("XYBERAH_MAX_CONCURRENT_CAMPAIGNS", "1"))
        self.grader = os.getenv("XYBERAH_GRADER", "openai:chat:gpt-4.1-mini")
        # Built-in vulnerable demo target, reachable from tool subprocesses in-container
        self.demo_url = os.getenv("XYBERAH_DEMO_URL", "http://127.0.0.1:8000/api/demo/chat")

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.campaigns_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.secret_key = os.getenv("XYBERAH_SECRET_KEY") or self._persisted_secret()

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'xyberah.db'}"

    @property
    def campaigns_dir(self) -> Path:
        return self.data_dir / "campaigns"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    def _persisted_secret(self) -> str:
        # Generated once and kept in the data volume so sessions survive restarts
        path = self.data_dir / ".secret_key"
        if not path.exists():
            path.write_text(secrets.token_urlsafe(48))
            path.chmod(0o600)
        return path.read_text().strip()


@lru_cache
def get_settings() -> Settings:
    return Settings()
