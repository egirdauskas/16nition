"""Approved existing Store configuration for new accounts; no feature admission."""
from copy import deepcopy
import json
from pathlib import Path

from .store_single_consumables import catalog as _catalog
from .policy_memo import policy_memo
from .store_demo_offers import marker_for


@policy_memo
def _initial_products():
    """Pure current certified base catalog; no receipts or account state."""
    return _catalog()


def initial_store(account):
    """Return account-bound Store configuration documents without writing them."""
    account = Path(account).resolve()
    return {
        "products.json": deepcopy(_initial_products()),
        "store-demo-offers.json": marker_for(account),
    }


@policy_memo
def initial_control():
    """Use implemented scoped handlers; unknown operations still have no reply.

    Keep explicit optional-request closes. This avoids binding fresh accounts
    to the normal account's item-specific transport URLs or old hold probes.
    """
    path = Path(__file__).parent / 'data/roster-control.json'
    value = json.loads(path.read_bytes())
    value['successor'] = 'pass'
    value['victory'] = 'pass'
    for operation in (
        'PUT /ut/game/fifaworldmobile/clientdata/favTeam',
        'POST /ut/game/fifaworldmobile/user',
        'POST /victory_fwm_s2/Engine.svc/User/Persona/SaveFavorites',
        'POST /victory_fwm_s2/Engine.svc/Challenge/ReportEvent',
        'GET /victory_fwm_s2/Engine.svc/Challenge/GetChallenges',
        'GET /victory_fwm_s2/Engine.svc/Challenge/GetRewardsToClaim',
        'GET /ut/game/fifaworldmobile/store/purchasegroup/all?ppInfo=true&categoryInfo=true',
        'GET /ut/game/fifaworldmobile/tradePile',
        'GET /ut/game/fifaworldmobile/watchList?offset=0&count=30',
    ):
        value['requests'][operation] = 'pass'
    return value
