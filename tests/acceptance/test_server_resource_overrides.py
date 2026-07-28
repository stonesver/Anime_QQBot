"""Acceptance tests for the 2 GiB production Compose overlay."""

from __future__ import annotations

import json
import os
import subprocess


def test_server_overlay_applies_confirmed_resource_limits() -> None:
    env = os.environ.copy()
    env.update(
        {
            "POSTGRES_PASSWORD": "test-password",
            "ONEBOT_TOKEN": "123456789012345678901234",
            "BANGUMI_USER_AGENT": "anime-qqbot/test test@example.com",
        }
    )
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "compose.yaml",
            "-f",
            "compose.server-2g.yaml",
            "config",
            "--format",
            "json",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    expected = {
        "postgres": ("201326592", "67108864", 0.5),
        "migrate": ("268435456", None, 0.5),
        "worker": ("201326592", "67108864", 0.5),
        "astrbot": ("536870912", "268435456", 0.8),
        "napcat": ("536870912", "268435456", 0.8),
    }
    for service, (memory, reservation, cpus) in expected.items():
        assert str(services[service]["mem_limit"]) == memory
        assert services[service].get("mem_reservation") in (
            reservation,
            int(reservation) if reservation else None,
        )
        assert float(services[service]["cpus"]) == cpus
        assert services[service]["pids_limit"] == 256
