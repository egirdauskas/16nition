"""Account ownership context shared by tournament match and reward paths."""

import json
import uuid
from pathlib import Path


def context(account):
    """Return (account owner, active Seasons match, prepared Seasons intent).

    A missing journal is valid only for a fully published first-run account.
    Existing journals are parsed independently and never fall back to setup
    metadata when corrupt or incomplete.
    """
    account = Path(account)
    path = account / "native-seasons.json"
    if path.exists():
        value = json.loads(path.read_bytes())
        required = {"account_id", "active_match", "prepared"}
        if type(value) is not dict or not required <= value.keys():
            raise ValueError("Invalid native Seasons owner context")
        uuid.UUID(value["account_id"])
        return value["account_id"], value["active_match"], value["prepared"]

    from .first_run_account import inspect

    setup = inspect(account)
    return setup["account_id"], None, None
