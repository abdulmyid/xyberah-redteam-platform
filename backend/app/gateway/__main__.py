"""Run the AI Firewall: ``python -m app.gateway`` (listens on 0.0.0.0:8080)."""
import logging
import os

import uvicorn


def main() -> None:
    """Start uvicorn with gateway-appropriate settings."""
    logging.basicConfig(level=os.getenv("XYBERAH_GATEWAY_LOG_LEVEL", "INFO").upper(),
                        format="%(message)s" if os.getenv("XYBERAH_GATEWAY_JSON_ONLY") else
                        "%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run(
        "app.gateway.server:app",
        host=os.getenv("XYBERAH_GATEWAY_HOST", "0.0.0.0"),
        port=int(os.getenv("XYBERAH_GATEWAY_PORT", "8080")),
        access_log=False,              # the gateway writes its own structured audit trail
        server_header=False,
        proxy_headers=False,           # client IP is derived from X-Forwarded-For by trusted-peer rules
        timeout_keep_alive=30,
        timeout_graceful_shutdown=20,
        log_level=os.getenv("XYBERAH_GATEWAY_LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
