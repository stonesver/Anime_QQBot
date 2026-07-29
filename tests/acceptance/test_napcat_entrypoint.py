from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def test_entrypoint_migrates_existing_account_specific_onebot_config(
    tmp_path: Path,
) -> None:
    templates = tmp_path / "templates"
    config = tmp_path / "config"
    templates.mkdir()
    config.mkdir()
    account_config = config / "onebot11_123456.json"
    account_config.write_text('{"network":{"httpServers":[]}}')
    upstream = tmp_path / "upstream.sh"
    upstream.write_text("#!/bin/bash\nexit 0\n")
    upstream.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "ONEBOT_TOKEN": "test-token-with-at-least-24-chars",
            "NAPCAT_TEMPLATE_PATH": str(templates / "astrbot.json"),
            "NAPCAT_CONFIG_DIR": str(config),
            "NAPCAT_UPSTREAM_ENTRYPOINT": str(upstream),
        }
    )

    result = subprocess.run(
        ["bash", "scripts/napcat-entrypoint.sh"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(account_config.read_text())
    assert payload["network"]["httpServers"][0]["port"] == 3000
    assert payload["network"]["httpServers"][0]["token"] == env["ONEBOT_TOKEN"]
    assert payload["network"]["websocketClients"][0]["url"] == "ws://astrbot:6199/ws"
