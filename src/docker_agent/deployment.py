from __future__ import annotations

import json
import sys

from pydantic import ValidationError
from sqlalchemy.engine import make_url

from docker_agent.config import (
    Settings,
    require_application_runtime_settings,
    settings_env_file,
)


def production_preflight(
    *,
    env_file: str | None = ".env.production",
) -> int:
    """Validate production runtime settings and print a secret-safe summary."""

    resolved_env_file = (
        settings_env_file("production")
        if env_file == ".env.production"
        else env_file
    )

    try:
        settings = Settings(
            _env_file=resolved_env_file,
            app_env="production",
        )
        require_application_runtime_settings(settings)
    except ValidationError as exc:
        payload = {
            "status": "error",
            "errors": [
                {
                    "field": ".".join(
                        str(item) for item in error["loc"]
                    ),
                    "message": error["msg"],
                }
                for error in exc.errors(
                    include_input=False,
                    include_url=False,
                )
            ],
        }
        print(
            json.dumps(payload, ensure_ascii=False, indent=2),
            file=sys.stderr,
        )
        return 2
    except ValueError as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "errors": [
                        {
                            "field": "runtime",
                            "message": str(exc),
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2

    database = make_url(settings.database_url)
    payload = {
        "status": "ok",
        "app_env": settings.app_env,
        "database": {
            "backend": database.get_backend_name(),
            "host": database.host,
            "port": database.port,
            "database": database.database,
        },
        "model": {
            "name": settings.model_name,
            "api_key_configured": bool(settings.model_api_key),
        },
        "tool_mode": settings.tool_mode,
        "local_docker_tools_allowed": settings.allow_local_docker_tools,
        "migration_config": settings.database_migration_config,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0
