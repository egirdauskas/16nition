"""Fixed special rates for regular packs (revival_policy pack_special_rates_v1).

Before this policy a special was ranked like any other rare item, so the chance
of a special grew with every admitted special, and every special (even one
built on a non-rare base card) could only fill a rare slot.

With the policy active:
- specials fill the slot kind of their base card (rare or non-rare);
- each slot first decides "special or not", then the existing deterministic
  rank picks within that subset;
- per tier, the rare-slot chance is the policy rate r (capped at the natural
  share s_rare, so nothing becomes likelier than before). The same scale factor
  k = rare chance / s_rare applies to non-rare slots: chance = k * s_common,
  where s_common is the non-rare-based specials' share of the non-rare pool
  (user decision 7 Nov 2026: proportional to the pool).
"""
from fractions import Fraction
import hashlib
import json
from pathlib import Path

from .policy_memo import policy_memo

POLICY = Path(__file__).parent / 'policy' / 'pack-special-rates-v1.json'
TIERS = ('bronze', 'silver', 'gold')


@policy_memo
def policy():
    value = json.loads(POLICY.read_text())
    for field in ('rare_slot_special_per_mille', 'non_rare_slot_special_per_mille'):
        rates = value.get(field)
        if (type(rates) is not dict or set(rates) != set(TIERS)
                or any(type(r) is not int or not 0 <= r <= 1000 for r in rates.values())):
            raise ValueError('Invalid pack special rate policy')
    if (value.get('classification') != 'revival_policy' or value.get('version') != 'pack_special_rates_v1'
            or type(value.get('active')) is not bool):
        raise ValueError('Invalid pack special rate policy')
    return value


def rates_for(rule):
    """{tier: per mille} when the policy applies to this rule, else None."""
    value = policy()
    if not value['active'] or rule.get('selection') not in value['selections']:
        return None
    return dict(value['rare_slot_special_per_mille'])


def non_rare_caps():
    """{tier: per mille} fixed ceiling for a non-rare slot."""
    return dict(policy()['non_rare_slot_special_per_mille'])


def slot_rare(item):
    """Slot kind under the policy: a special follows its base card's rarity."""
    return bool(item.base_rare)


def probabilities(eligible, rates, non_rare=None):
    """{(tier, rare): Fraction} chance that a slot of that kind is a special.

    non_rare: optional {tier: per mille} ceiling for non-rare slots (policy default when None).
    """
    if non_rare is None:
        non_rare = non_rare_caps()
    result = {}
    for tier in TIERS:
        share = {}
        for rare in (True, False):
            items = [i for i in eligible if i.base_quality == tier and slot_rare(i) == rare]
            specials = sum(1 for i in items if i.special_version_id)
            share[rare] = Fraction(specials, len(items)) if items else Fraction(0)
        target = Fraction(rates[tier], 1000)
        if share[True]:
            scale = min(Fraction(1), target / share[True])
        else:
            scale = min(Fraction(1), target / share[False]) if share[False] else Fraction(0)
        result[tier, True] = scale * share[True]
        result[tier, False] = min(scale * share[False], Fraction(non_rare[tier], 1000))
    return result


def wants_special(seed, slot, probability):
    digest = hashlib.sha256(('pack_special_rates_v1:%s:%d' % (seed, slot)).encode()).digest()
    return int.from_bytes(digest[:8], 'big') < probability * 2 ** 64


def pick(ordered, count, probability, seed, usable):
    """Choose count items from the ranked list, deciding special-or-not per slot.

    usable(item, chosen) applies the caller's existing uniqueness constraints.
    """
    specials = [item for item in ordered if item.special_version_id]
    ordinary = [item for item in ordered if not item.special_version_id]
    chosen = []
    for slot in range(count):
        first, second = (specials, ordinary) if wants_special(seed, slot, probability) else (ordinary, specials)
        item = next((c for c in first if usable(c, chosen)), None)
        if item is None:
            item = next((c for c in second if usable(c, chosen)), None)
        if item is None:
            break
        chosen.append(item)
    return chosen


def counts_rare(item, rule):
    """Whether an item fills a rare slot of this rule under the active policy."""
    if rates_for(rule):
        return slot_rare(item)
    from .local_packs import mixed_counts_rare
    return mixed_counts_rare(item, rule)


def special_weight_multipliers(pool, rates):
    """{(tier, rare): weight factor} for weighted draws (reviewed_specials_sha256_without_replacement).

    Those packs rank every candidate by weight; with factor m on specials the chance that a pick
    is a special is m*S / (m*S + B) for S specials and B ordinary items of equal base weight in
    the group. m is chosen so that chance equals the same per-slot target as regular packs.
    """
    chances = probabilities(pool, rates)
    result = {}
    for (tier, rare), target in chances.items():
        group = [i for i in pool if i.base_quality == tier and slot_rare(i) == rare]
        specials = sum(1 for i in group if i.special_version_id)
        ordinary = len(group) - specials
        if specials == 0 or ordinary == 0 or target <= 0:
            result[tier, rare] = Fraction(0)
        else:
            result[tier, rare] = target * ordinary / (specials * (1 - target))
    return result
