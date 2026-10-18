"""Device catalog, independent of wallet authority and mutable relay state.

Declaring a profile never activates it on a commissioned controller.
"""
from copy import deepcopy

WASH_OUTPUTS={'water':0,'osmos':1,'nano':2,'foam':3,'wax':4,'chem':5,'vacuum':6,'air':7}
FOG_OUTPUTS={**{f'aroma_{i}':i-1 for i in range(1,6)},'blackening':5,'tank_air':6,'purge':7}
FOG_NAMES=['SHEIKH SULTAN','BLACK ICE','NARCOTIC','INVICTUS CREED','ANTI-TOBACCO']

def device_kind(value=None):
    if value is None:return 'wash'
    if value not in ('wash','dry_fog'):raise ValueError('Unknown device type')
    return value

def profile(kind=None):
    kind=device_kind(kind)
    if kind=='wash':
        return {'type':'wash','outputs':deepcopy(WASH_OUTPUTS),'client_programs':list(WASH_OUTPUTS),'technical_outputs':[],'requires_trigger':True}
    ids=[f'aroma_{i}' for i in range(1,6)]+['blackening','tank_air']
    return {'type':kind,'outputs':deepcopy(FOG_OUTPUTS),'client_programs':ids,'primary_programs':ids[:5],'additional_programs':ids[5:],
            'technical_outputs':['purge'],'requires_trigger':False,
            'defaults':{'tariffs':{p:{'amountSum':1000,'durationSeconds':1,'enabled':True} for p in ids},
                        'pauseEnabled':True,'freePauseSeconds':300,'paidPause':{'enabled':True,'amountSum':250,'durationSeconds':1},
                        'purge':{'enabled':False,'idleSeconds':7200,'durationSeconds':30}},
            'live_activation_ready':False}

def catalog():
    return {'ok':True,'version':1,'profiles':[profile('wash'),profile('dry_fog')]}
