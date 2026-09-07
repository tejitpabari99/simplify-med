import os
import subprocess
import sys
import textwrap
from pathlib import Path


def test_app_imports_from_backend_workdir_layout():
    backend_dir = Path(__file__).resolve().parents[2]
    script = textwrap.dedent(
        """
        from unittest.mock import patch

        with patch("utils.firebase.initialize_firebase", return_value=None):
            import app  # noqa: F401
        """
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"


def test_preflight_includes_cors_headers():
    backend_dir = Path(__file__).resolve().parents[2]
    script = textwrap.dedent(
        """
        from unittest.mock import patch

        with patch("utils.firebase.initialize_firebase", return_value=None):
            import app as app_module

        client = app_module.app.test_client()
        response = client.open(
            "/health",
            method="OPTIONS",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,content-type,x-session-id",
            },
        )

        assert response.status_code == 200, response.status_code
        assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
        assert "authorization" in response.headers["Access-Control-Allow-Headers"]
        """
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
