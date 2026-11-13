"""Isolated startup profile read experiment, never a fixture XP/Awards producer."""
import hashlib,json
from pathlib import Path
from .account_progression import level_state
from .local_profile import load_profile

class ProfilePlateProjection:
    def __init__(self,policy,profile_path):
        self.path=Path(profile_path).resolve();root=Path(__file__).resolve().parents[1]
        if root/'reports' not in self.path.parents or self.path.parent.name!='isolated-account':
            raise ValueError('Isolated reports profile required')
        if Path(profile_path).is_symlink():raise ValueError('Profile alias refused')
        real=root/'server/data/development/fm16in2026/profile.json'
        if real.exists() and self.path.samefile(real):raise ValueError('Real profile alias refused')
        self.policy=json.loads(Path(policy).read_text())
        self.display=self.policy.get('policy_version')=='profile_plate_projection_display_test_v2'
        expected={'schema','classification','policy_version','profile_sha256','delta_experience','delta_level_experience'}
        if self.display:expected.add('field_semantics')
        if set(self.policy)!=expected or type(self.policy['schema']) is not int or self.policy['schema']!=1:
            raise ValueError('Invalid isolated profile projection schema')
        if self.display:
            if (self.policy['classification']!='isolated_profile_display_projection' or
                self.policy['field_semantics']!='within_level_and_requirement_candidate' or
                any(type(self.policy[k]) is not int or self.policy[k]<0 for k in ('delta_experience','delta_level_experience'))):
                raise ValueError('Explicit bounded profile display candidate required')
        elif (self.policy['classification']!='isolated_zero_delta_profile_projection' or
              self.policy['policy_version']!='profile_plate_projection_test_v1' or
              any(type(self.policy[k]) is not int or self.policy[k]!=0 for k in ('delta_experience','delta_level_experience'))):
            raise ValueError('Only explicit zero-delta v1 profile projection allowed')
        self.fields()
    def fields(self):
        if hashlib.sha256(self.path.read_bytes()).hexdigest()!=self.policy['profile_sha256']:
            raise ValueError('Projection profile differs from archived pin')
        profile=load_profile(self.path)
        if profile.revival_total_xp is None:raise ValueError('Explicit backend XP snapshot required')
        state=level_state(profile.revival_total_xp)
        # This bounded probe tests field consumption, not unknown unbounded wire
        # ranges or cumulative/within-level historical semantics.
        if state['total_xp']>10000 or state['level']>10:raise ValueError('Projection probe exceeds bounded range')
        if self.display:
            #00325044 ->002fd9c8 ->0091fdb8 ->00a6ccfc directly copies these
            #two members to UserPlateManager+48/+50. The supplied Lua calls
            #them currentXP/targetXP. This isolated candidate tests a derived
            #within-level display; it is not an Awards delta or fixture grant.
            if (self.policy['delta_experience'],self.policy['delta_level_experience'])!=(state['level_xp'],state['next_level_xp']):
                raise ValueError('Profile display must match pinned progression snapshot')
            return {'DeltaExperience':state['level_xp'],'DeltaLvExp':state['next_level_xp'],'Level':state['level']}
        return {'DeltaExperience':0,'DeltaLvExp':0,'Experience':state['total_xp'],
                'Level':state['level'],'NextLvExp':state['next_level_xp']}
