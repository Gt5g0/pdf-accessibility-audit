"""Create an authenticated Box SDK client (developer-token auth).

This module is only used when ``source: box`` is selected in configuration.
"""

from __future__ import annotations

from typing import Any, Dict

from box_sdk_gen import BoxClient, BoxDeveloperTokenAuth


def create_box_client(cfg: Dict[str, Any]) -> BoxClient:
    """Build a ``BoxClient`` from ``cfg['box']['developer_token']``.

    Raises:
        ValueError: If the ``box`` mapping or token is missing/blank.
    """

    box = cfg.get("box")
    if not isinstance(box, dict):
        raise ValueError("config must include a 'box' mapping when using Box.")

    token = str(box.get("developer_token") or "").strip()
    if not token:
        raise ValueError(
            "When source is box, set box.developer_token to your Developer Token from "
            "the Box Developer Console (Configuration → Developer Token)."
        )

    auth = BoxDeveloperTokenAuth(token=token)
    return BoxClient(auth=auth)
