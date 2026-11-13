#!/usr/bin/env python3
"""Frozen original season-prize screen proof; read-only and presentation scoped."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.lab_evidence import file_digest
from server.native_season_coin_rewards import SEASON_PRIZE_PROJECTION,awards_response

DEFAULT=ROOT/'reports/ui-audit/2026-11-02'

def read(path):return json.loads(Path(path).read_bytes())

def inspect(root=DEFAULT):
    root=Path(root).resolve();lab=root/'season-display-lab'
    before=read(lab/'candidate-ready/profile.json');after=read(lab/'final-account/profile.json')
    state=read(lab/'final-account/native-seasons.json')
    if state['active_match'] or state['prepared'] or len(state['matches'])!=1 or len(state['completions'])!=1:
        raise ValueError('One quiescent isolated completion required')
    source=state['matches'][0];outcome=state['completions'][0]['outcome']
    if (not source.get('native_atomic_final') or source['score']!=[2,0] or
            source['season_coin_start'].get('native_awards_projection')!=SEASON_PRIZE_PROJECTION):
        raise ValueError('Genuine accepted source or display snapshot differs')
    reply=awards_response(source['season_coin_start'],outcome,source['reward_coins'])
    if source['response']!=dict(reply,seasonEndResult=outcome['preview_band']) or reply!={
            'matchCoins':30750,'participationAward':2250,'seasonCoins':28500}:
        raise ValueError('Source display differs from pinned payout')
    from scripts.read_capture_events import read_events
    delivered=[row for row in read_events(ROOT/'captures/run-1329/reachability.jsonl')
        if row.get('action')=='released_pass' and row.get('response') and
        row.get('request','').startswith('PUT /ut/game/fifaworldmobile/match/sim/end HTTP/1.1')]
    if len(delivered)!=1 or delivered[0]['request'].split('\r\n\r\n',1)[1].encode('latin1').hex()!=source['end_body_hex'] or json.loads(delivered[0]['response'].split('\r\n\r\n',1)[1])!=source['response']:
        raise ValueError('Original captured End response differs from committed source')
    expected=dict(before,credits=before['credits']+30750,revival_total_xp=100,division_offline=9)
    if after!=expected or len(state.get('season_coin_rewards',[]))!=1:
        raise ValueError('Wallet/profile changed beyond original grants')
    bonus=state['season_coin_rewards'][0]
    if bonus['amount']!=28500 or source['reward']['id']==bonus['id']:
        raise ValueError('Match and season transaction identities differ from proof')
    abort=read(lab/'abort-zero-effects.json')
    if not abort['profile_unchanged'] or not abort['season_unchanged'] or abort['old_source_reward'] is not None:
        raise ValueError('Negative held attempt changed economic state')
    owners=read(ROOT/'captures/run-1329/prize-awards-values.json')['fields']
    if (owners['coinsExtra'],owners['coinsBonus'],owners['coinsTotal'],owners['xpTotal'])!=(2250,28500,30750,100):
        raise ValueError('Original Awards physical totals differ')
    cold=read(ROOT/'captures/run-1330/cold-user-info.json')['fields']
    plate=read(ROOT/'captures/run-1330/cold-profile.json')['owners']['UserPlateManager']['words']
    if (cold['coins'],cold['points'],plate['0x5c'],plate['0x48'])!=(after['credits'],after['fifa_points'],1,100):
        raise ValueError('Cold native wallet/XP differs')
    if read(lab/'backend-restart/result.json')['delta']['identical'] is not True:
        raise ValueError('Backend restart changed account')
    for when in ('before','after'):
        for operation in ('report','end'):
            proof=read(lab/f'{operation}-retries-{when}-restart/proof.json')
            if proof['count']!=3 or not proof['all_account_json_unchanged'] or not proof['real_account_unchanged']:
                raise ValueError('Exact transport retry proof incomplete')
    for number in (1329,1330):
        meta=read(ROOT/f'captures/run-{number}/metadata.json')
        if not meta.get('finished_utc') or Path(meta['startup_control_source']).resolve()!=lab/'isolated-account/control.json':
            raise ValueError('Original same-account frozen capture required')
    return dict(status='STOCK_VERIFIED_SEASON_PRIZE_DISPLAY',native_capture=1329,cold_capture=1330,
        source_id=source['id'],season_coins=28500,total_coins=30750,exact_retries=12,
        scope='Authorized isolated screen fixture; no new natural-traversal claim',
        stock_screen='PauseMenuOffline/SeasonsPostmatchOptions',wallet_unchanged_by_display=True)


def verify(root=DEFAULT):
    root=Path(root).resolve();certificate=read(root/'season-prize-certificate.json')
    if certificate['proof']!=inspect(root) or certificate.get('user_visual_accepted') is not True:
        raise ValueError('Display certificate or user acceptance differs')
    for name,digest in certificate['files'].items():
        path=(ROOT/name).resolve()
        if not any(p in path.parents for p in (ROOT/'reports',ROOT/'captures')) or path.is_symlink() or file_digest(path)!=digest:
            raise ValueError('Display certificate evidence changed: '+name)
    return certificate['proof']


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=DEFAULT)
    print(json.dumps(verify(p.parse_args().root)))
