"""Identifier catalog recovered from original libfifa.so table027aa6e8.

010303bc/01030604 decode/encode these17 pairs. These are content/protocol
identifiers, not invented positions or formation asset data.
"""
FORMATIONS={
    1:'f3412',3:'f3421',5:'f343',7:'f352',9:'f41212',11:'f4231',
    13:'f4222',15:'f4312',17:'f4321',19:'f433',21:'f4411',23:'f442',
    25:'f451',27:'f5212',29:'f5221',31:'f532',33:'f541',
}

def validate_formation(identifier):
    if type(identifier) is not int or identifier not in FORMATIONS:
        raise ValueError('Unknown original-client formation identifier')
    return identifier
