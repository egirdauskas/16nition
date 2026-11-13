"""Shared pure 3/1/0 rules; never decode or manufacture opaque stock records."""
POINTS={'W':3,'D':1,'L':0}
MATCHES_PER_SEASON=10

def validate_progress(played,points):
    if type(played) is not int or type(points) is not int or not 0<=played<=MATCHES_PER_SEASON:
        raise ValueError('Invalid season progress')
    if not any(POINTS['W']*wins+POINTS['D']*draws==points for wins in range(played+1) for draws in range(played-wins+1)):
        raise ValueError('Points cannot arise from stock win/draw/loss outcomes')
    return played,points

def advance(played,points,result):
    validate_progress(played,points)
    if type(result) is not str or result not in POINTS or played==MATCHES_PER_SEASON:
        raise ValueError('Invalid or completed fixture')
    return validate_progress(played+1,points+POINTS[result])


def reconcile(played, points, next_played, next_points):
    """Check one externally generated progression against the simulator rules.

    This recognizes aggregate outcome only; it establishes no match identity,
    score, native record contents, completion contract or reward eligibility.
    """
    validate_progress(played, points);validate_progress(next_played, next_points)
    if (played, points)==(next_played, next_points):return None
    if next_played!=played+1:raise ValueError('Out-of-order genuine progress')
    result=next((r for r,p in POINTS.items() if p==next_points-points),None)
    if result is None or advance(played,points,result)!=(next_played,next_points):
        raise ValueError('Native progress contradicts shared 3/1/0 rules')
    return result
