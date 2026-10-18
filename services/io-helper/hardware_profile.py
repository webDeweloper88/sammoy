"""Fail closed for dry-fog output maps; legacy wash config remains supported."""
WASH_OUTPUTS={'water':0,'osmos':1,'nano':2,'foam':3,'wax':4,'chem':5,'vacuum':6,'air':7}
FOG_OUTPUTS={**{f'aroma_{i}':i-1 for i in range(1,6)},'blackening':5,'tank_air':6,'purge':7}

def validate_profile(cfg):
    kind=cfg.get('device_type','wash')
    if kind not in ('wash','dry_fog'):raise ValueError('Unknown hardware device type')
    if kind=='dry_fog':
        rows=cfg.get('outputs',[])
        if any(type(r.get('address')) is not int for r in rows) or len(rows)!=8 or {r.get('name'):r.get('address') for r in rows}!=FOG_OUTPUTS:
            raise ValueError('Dry fog requires the dedicated seven services plus purge output map')
        if cfg.get('safety',{}).get('startup_all_off') is not True:raise ValueError('Dry fog requires startup all-off')
    return kind
