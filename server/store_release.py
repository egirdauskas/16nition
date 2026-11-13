"""Explicit, backed-up local Store deployment. No gameplay/reward admission.

This is configuration validation, not an additional transaction framework.
The existing purchase, pack and inventory journals remain authoritative.
"""
import hashlib
import json
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT/'server/data/development/fm16in2026'
MARKER = 'store-release.json'
ACCOUNT = None
POLICY = None
FILES = ('profile.json','football.json','content.json','packs.json',
         'seasons.json','definition.json','control.json')
IDENTITY = ('identity_pid','persona_id','user_id')
_CONSTRUCTOR_VALIDATION = ContextVar('store_constructor_validation', default=None)
_UPGRADE_VALIDATION = ContextVar('store_upgrade_validation', default=False)


def reuse_store_validation(constructor):
    """Share one Store check only within a read-only coordinator constructor.

    Every construction starts empty. Never wrap recovery, response handling or
    mutation methods: their account state can change after preparation.
    """
    @wraps(constructor)
    def scoped(instance, account, *args, **kwargs):
        # Preserve the constructor's selector/error order. Resolve lazily only
        # if its read-only validation path actually reaches the Store.
        token = _CONSTRUCTOR_VALIDATION.set({'account':account, 'resolved_account':None, 'policy':None})
        try:
            return constructor(instance, account, *args, **kwargs)
        finally:
            _CONSTRUCTOR_VALIDATION.reset(token)
    return scoped

def archive(path, manifest_sha):
    path = Path(path).resolve()
    if not any(ROOT/area in path.parents for area in ('reports/store-release','reports/store-fp-options','reports/store-consumable-packs','reports/club-item-packs','reports/pack-spec-alignment')):
        raise ValueError('Store deployment needs a separate release backup')
    manifest = path/'.lab-snapshot.json'
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != manifest_sha:
        raise ValueError('Store backup manifest changed')
    value = json.loads(manifest.read_bytes())
    if not (set(FILES)|{'products.json','purchases.json'}) <= value['sha256'].keys():
        raise ValueError('Incomplete Store backup')
    for name, sha in value['sha256'].items():
        p = path/name
        if Path(name).name != name or p.is_symlink() or p.stat().st_nlink != 1 or hashlib.sha256(p.read_bytes()).hexdigest() != sha:
            raise ValueError('Store backup changed')
    return path

def validate(account):
    account = Path(account).resolve()
    scope = _CONSTRUCTOR_VALIDATION.get()
    if scope is not None and scope['resolved_account'] is None:
        scope['resolved_account'] = Path(scope['account']).resolve()
    if scope is not None and scope['resolved_account'] == account:
        if scope['policy'] is None:
            scope['policy'] = _validate(account)
        # Callers cannot change another validator's view of the checked policy.
        return deepcopy(scope['policy'])
    return _validate(account)


def _validate(account):
    account = Path(account).resolve()
    from .store_single_candidate import selection as single_selection
    single = single_selection(account)
    from . import gameplay_release
    candidate=account!=REAL and gameplay_release.selected(account)
    if candidate:gameplay_release.validate(account)
    if account != REAL and not candidate:
        raise ValueError('Store deployment account differs')
    for p in account.glob('*.json'):
        if p.is_symlink() or p.stat().st_nlink != 1:
            raise ValueError('Store account aliases refused')
    policy = json.loads((account/MARKER).read_bytes())
    base={'version','account','origin_archive','origin_manifest_sha256','products_sha256','presentation_sha256'}
    spec=policy.get('version')=='local_store_release_v5'
    club=policy.get('version') in ('local_store_release_v4','local_store_release_v5')
    specialist=policy.get('version') in ('local_store_release_v3','local_store_release_v4','local_store_release_v5')
    upgrade=policy.get('version') in ('local_store_release_v2','local_store_release_v3','local_store_release_v4','local_store_release_v5')
    keys=base|{'upgrade_archive','upgrade_manifest_sha256','fp_policy_sha256'} if upgrade else base
    if specialist:keys|={'specialist_archive','specialist_manifest_sha256','specialist_policy_sha256','specialist_certificate','specialist_certificate_sha256'}
    if club:keys|={'club_archive','club_manifest_sha256','club_policy_sha256','club_quick_sell_policy_sha256','club_certificate','club_certificate_sha256'}
    if spec:keys|={'spec_archive','spec_manifest_sha256','spec_policy_sha256','spec_certificate','spec_certificate_sha256'}
    if spec and 'pool_amendment' in policy:keys.add('pool_amendment')
    if spec and 'pack_family_split' in policy:keys.add('pack_family_split')
    if (set(policy) != keys or policy['version'] not in ('local_store_release_v1','local_store_release_v2','local_store_release_v3','local_store_release_v4','local_store_release_v5') or policy['account'] != str(REAL if candidate else account)):
        raise ValueError('Invalid Store deployment marker')
    origin = archive(policy['origin_archive'], policy['origin_manifest_sha256'])
    from .native_paid_pack_presentation import MARKER as PAID
    for name, key in [('products.json','products_sha256'),(PAID,'presentation_sha256')]:
        source = single['archive'] if single is not None and name == 'products.json' else account
        if hashlib.sha256((source/name).read_bytes()).hexdigest() != policy[key]:
            raise ValueError('Store deployment configuration changed')
    before = json.loads((origin/'profile.json').read_bytes())
    current = json.loads((account/'profile.json').read_bytes())
    if any(before[k] != current[k] for k in IDENTITY):
        raise ValueError('Store deployment identity changed')
    from .classic_pack_store import projection, POLICY_V11
    expected = projection(POLICY_V11,backend_only=True)['products']
    for i, row in enumerate(expected):row['product_id'] = 47001+i
    expected={'persona_id':1,'products':expected}
    if upgrade:
        prior=archive(policy['upgrade_archive'],policy['upgrade_manifest_sha256'])
        previous=json.loads((prior/MARKER).read_bytes())
        if previous['version']!='local_store_release_v1' or previous['origin_archive']!=str(origin):raise ValueError('FP upgrade requires archived deployed coin Store')
        from .store_fp_policy import catalog, PATH as FP_PATH
        if hashlib.sha256(FP_PATH.read_bytes()).hexdigest()!=policy['fp_policy_sha256']:raise ValueError('FP price book changed')
        expected=catalog()
    if specialist:
        prior=archive(policy['specialist_archive'],policy['specialist_manifest_sha256'])
        previous=json.loads((prior/MARKER).read_bytes())
        if previous['version']!='local_store_release_v2' or previous['origin_archive']!=str(origin):
            raise ValueError('Specialist upgrade requires archived certified FP Store')
        from .specialist_consumable_packs import catalog,PATH as SPECIALIST_PATH
        if hashlib.sha256(SPECIALIST_PATH.read_bytes()).hexdigest()!=policy['specialist_policy_sha256']:
            raise ValueError('Specialist approved policy changed')
        certificate=Path(policy['specialist_certificate']).resolve()
        if ROOT/'reports/store-consumable-packs' not in certificate.parents or certificate.is_symlink() or hashlib.sha256(certificate.read_bytes()).hexdigest()!=policy['specialist_certificate_sha256']:
            raise ValueError('Specialist native certificate changed')
        proof=json.loads(certificate.read_bytes())
        if proof.get('catalog_version')!='local_store_catalog_v3' or proof.get('status')!='STOCK_VERIFIED':
            raise ValueError('Specialist native certificate incomplete')
        expected=catalog()
    if club:
        prior=archive(policy['club_archive'],policy['club_manifest_sha256'])
        previous=json.loads((prior/MARKER).read_bytes())
        if previous['version']!='local_store_release_v3' or previous['origin_archive']!=str(origin):
            raise ValueError('Club-item upgrade requires archived certified specialist Store')
        from .club_item_packs import catalog,PATH as CLUB_PATH
        from .quick_sell_policy import CLUB_PATH as CLUB_QUICK_SELL_PATH
        for path,key in ((CLUB_PATH,'club_policy_sha256'),(CLUB_QUICK_SELL_PATH,'club_quick_sell_policy_sha256')):
            if hashlib.sha256(path.read_bytes()).hexdigest()!=policy[key]:raise ValueError('Club-item approved policy changed')
        certificate=Path(policy['club_certificate']).resolve()
        if ROOT/'reports/club-item-packs' not in certificate.parents or certificate.is_symlink() or hashlib.sha256(certificate.read_bytes()).hexdigest()!=policy['club_certificate_sha256']:
            raise ValueError('Club-item native certificate changed')
        proof=json.loads(certificate.read_bytes())
        if (proof.get('catalog_version')!='local_store_catalog_v4' or proof.get('status')!='STOCK_VERIFIED' or
            proof.get('families')!=['badge','ball','kit','stadium'] or proof.get('quick_sell_verified') is not True):
            raise ValueError('Club-item native certificate incomplete')
        expected=catalog()
    if spec:
        prior=archive(policy['spec_archive'],policy['spec_manifest_sha256'])
        previous=json.loads((prior/MARKER).read_bytes())
        if previous['version']!='local_store_release_v4' or previous['origin_archive']!=str(origin):
            raise ValueError('Exact-tier upgrade requires archived certified club-item Store')
        from .standard_pack_specs import catalog,PATH as SPEC_PATH
        if hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest()!=policy['spec_policy_sha256']:
            raise ValueError('Exact-tier approved policy changed')
        certificate=Path(policy['spec_certificate']).resolve()
        if ROOT/'reports/pack-spec-alignment' not in certificate.parents or certificate.is_symlink() or hashlib.sha256(certificate.read_bytes()).hexdigest()!=policy['spec_certificate_sha256']:
            raise ValueError('Exact-tier native certificate changed')
        proof=json.loads(certificate.read_bytes())
        if (proof.get('catalog_version')!='local_store_catalog_v5' or proof.get('status')!='STOCK_VERIFIED' or
            proof.get('consumer_club_items_verified') is not True or proof.get('standard_tiers_verified') is not True):
            raise ValueError('Exact-tier native certificate incomplete')
        expected=catalog()
    if spec and 'pack_family_split' in policy:
        from .pack_family_split import validate_deployment
        expected=validate_deployment(account,policy)
    elif spec and 'pool_amendment' in policy:
        from .store_pool_amendment import validate_deployment
        expected=validate_deployment(account,policy)
    actual = single['base_products'] if single is not None else json.loads((account/'products.json').read_bytes())
    if actual != expected:
        raise ValueError('Only the approved Store catalog is admitted')
    return policy

def configure(account=None):
    global ACCOUNT, POLICY
    ACCOUNT = POLICY = None
    if account is not None:
        account = Path(account).resolve()
        policy = validate(account)
        ACCOUNT, POLICY = account, policy

def selected(account):
    return ACCOUNT is not None and Path(account).resolve() == ACCOUNT

def configuration_preserved(account,origin):
    """Pinned gameplay Store bytes, or their exact certified v4 upgrade origin.

    Old gameplay admission markers remain immutable. Only the three Store
    configuration files may advance through the independently validated upgrade;
    its hash-verified backup must contain the exact bytes gameplay pinned.
    """
    names=('products.json',MARKER,'native-paid-pack-presentation.json')
    account,origin=Path(account).resolve(),Path(origin).resolve()
    same=lambda a,b:all(hashlib.sha256((a/n).read_bytes()).digest()==hashlib.sha256((b/n).read_bytes()).digest() for n in names)
    if same(account,origin):return True
    from .store_single_candidate import MARKER as SINGLE_MARKER, selection as single_selection
    single_marker = account / SINGLE_MARKER
    foreign = (
        single_marker.is_file() and not single_marker.is_symlink()
        and json.loads(single_marker.read_bytes()).get('account') != str(account)
    )
    # A selector copied from another account (e.g. a disposable copy of the
    # real account) never proves preservation; the caller refuses the change.
    single = None if foreign else single_selection(account)
    if single is not None and same(single['archive'], origin):
        return True
    if account!=REAL:
        from .gameplay_release import selected as gameplay_selected
        if not gameplay_selected(account) or _UPGRADE_VALIDATION.get():return False
    token=_UPGRADE_VALIDATION.set(True)
    try:
        policy=validate(account)
        archives=[policy['club_archive']] if policy['version'] in ('local_store_release_v4','local_store_release_v5') else []
        if policy['version']=='local_store_release_v5':archives.append(policy['spec_archive'])
        if 'pool_amendment' in policy:archives.append(policy['pool_amendment']['archive'])
        if 'pack_family_split' in policy:archives.append(policy['pack_family_split']['archive'])
        return any(same(Path(p),origin) for p in archives)
    except (OSError,ValueError,KeyError):return False
    finally:_UPGRADE_VALIDATION.reset(token)

def projection_account(paths):
    if not paths or any(p is None for p in paths):raise ValueError('Explicit Store selectors required')
    paths = [Path(p) for p in paths]
    account = paths[0].resolve().parent
    from . import fresh_account_runtime as fresh
    if fresh.selected(account):
        return fresh.validate_selectors(paths)
    if selected(account):
        if tuple(p.name for p in paths)!=FILES or any(p.is_symlink() or p.resolve().parent != account for p in paths):
            raise ValueError('Store selectors must share deployed account')
        validate(account)
        return account
    from .startup import validate_simulation_discovery
    result = validate_simulation_discovery(paths)
    if result.name != 'isolated-account':raise ValueError('Isolated Store account required')
    return result
