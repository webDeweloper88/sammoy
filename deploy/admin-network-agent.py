#!/usr/bin/python3
"""NetworkManager adapter. Root Unix socket; no public HTTP listener.
Reference: https://networkmanager.dev/docs/api/latest/gdbus-org.freedesktop.NetworkManager.html
"""
import dbus
from http.server import BaseHTTPRequestHandler
from socketserver import UnixStreamServer
import ipaddress
import json
import os
from pathlib import Path
import socket
import struct
import time
import uuid
import threading

NM='org.freedesktop.NetworkManager'
ROOT='/org/freedesktop/NetworkManager'
PROPS='org.freedesktop.DBus.Properties'
STATE=Path(os.environ.get('ADMIN_NETWORK_STATE','/var/lib/sammoy2-admin/network-pending.json'))
SOCKET=os.environ.get('ADMIN_NETWORK_SOCKET','/run/sammoy2-admin/network.sock')
TEMP=Path('/run/sammoy2-admin/temporary-wifi.json')
ACTION_LOCK=threading.RLock()

def read_temporary():
    try:return json.loads(TEMP.read_text())
    except (OSError,ValueError):return None

def save_temporary(value):
    TEMP.parent.mkdir(parents=True,exist_ok=True)
    temporary=TEMP.with_suffix('.tmp')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(value,stream)
    temporary.replace(TEMP)

def overlapping_networks(interfaces):
    networks={}
    for item in interfaces:
        if item.get('connected') and item.get('address'):
            try:networks[item['interface']]=ipaddress.ip_network(f"{item['address']}/{item['prefix']}",strict=False)
            except ValueError:pass
    return bool(networks.get('eth0') and networks.get('wlan0') and networks['eth0'].overlaps(networks['wlan0']))

class NetworkError(Exception):pass

def validate(payload):
    if not isinstance(payload,dict):raise ValueError('JSON object required')
    interface=str(payload.get('interface',''))
    if interface not in ('eth0','wlan0'):raise ValueError('Choose eth0 or wlan0')
    mode=payload.get('mode','dhcp')
    if mode not in ('dhcp','static'):raise ValueError('Choose DHCP or static IPv4')
    result={'interface':interface,'mode':mode}
    if payload.get('temporary'):
        if interface!='wlan0' or mode!='dhcp':raise ValueError('Temporary internet requires Wi-Fi with DHCP')
        result['temporary']=True
    if mode=='static':
        prefix=int(payload.get('prefix',24))
        if not 8<=prefix<=30:raise ValueError('Prefix must be between 8 and 30')
        address=ipaddress.IPv4Interface(str(payload.get('address',''))+'/'+str(prefix))
        gateway=ipaddress.IPv4Address(payload['gateway']) if payload.get('gateway') else None
        if not address.ip.is_private or address.ip.is_loopback or address.ip.is_link_local:raise ValueError('Use a LAN IPv4 address')
        if gateway is not None and (gateway not in address.network or gateway in (address.network.network_address,address.network.broadcast_address,address.ip)):raise ValueError('Gateway must be a different host in the same subnet')
        if address.ip in (address.network.network_address,address.network.broadcast_address):raise ValueError('Network and broadcast addresses cannot be assigned')
        dns=payload.get('dns') or ([str(gateway)] if gateway else [])
        if not isinstance(dns,list) or len(dns)>2:raise ValueError('Specify at most two DNS servers')
        result.update(address=str(address.ip),prefix=prefix,gateway=str(gateway) if gateway else '',dns=[str(ipaddress.IPv4Address(x)) for x in dns])
    if interface=='wlan0':
        ssid=str(payload.get('ssid',''));password=str(payload.get('password',''));security=payload.get('security','wpa-psk')
        if not 1<=len(ssid.encode())<=32 or any(ord(x)<32 for x in ssid):raise ValueError('Invalid Wi-Fi name')
        if not 8<=len(password)<=63 or any(ord(x)<32 for x in password):raise ValueError('Wi-Fi password must contain 8–63 characters')
        if security not in ('wpa-psk','sae'):raise ValueError('Only WPA2/WPA3 Personal is supported')
        result.update(ssid=ssid,password=password,security=security)
    return result

def connection_settings(config):
    profile={'connection':{'id':'SAMMOY '+config['interface'],'uuid':str(uuid.uuid4()),'type':'802-11-wireless' if config['interface']=='wlan0' else '802-3-ethernet','interface-name':config['interface'],'autoconnect':dbus.Boolean(False)},
             'ipv4':{'method':'auto' if config['mode']=='dhcp' else 'manual','route-metric':dbus.Int64(50)},'ipv6':{'method':'auto'}}
    if config['mode']=='static':
        profile['ipv4'].update({'address-data':dbus.Array([dbus.Dictionary({'address':config['address'],'prefix':dbus.UInt32(config['prefix'])},signature='sv')],signature='a{sv}'),
            'gateway':config['gateway'],'dns':dbus.Array([dbus.UInt32(struct.unpack('=I',socket.inet_aton(x))[0]) for x in config['dns']],signature='u'),'ignore-auto-dns':dbus.Boolean(True)})
    if config['interface']=='wlan0':
        profile['802-11-wireless']={'ssid':dbus.ByteArray(config['ssid'].encode()),'mode':'infrastructure','hidden':dbus.Boolean(True)}
        profile['802-11-wireless-security']={'key-mgmt':config['security'],'psk':config['password'],'psk-flags':dbus.UInt32(0)}
        if config['security']=='sae':profile['802-11-wireless-security']['pmf']=dbus.Int32(3)
        if config.get('temporary'):
            profile['connection']['id']='LABRIX temporary setup internet'
            for version in ('ipv4','ipv6'):
                profile[version]['route-metric']=dbus.Int64(5)
                profile[version]['dns-priority']=dbus.Int32(-50)
    else:profile['802-3-ethernet']=dbus.Dictionary({},signature='sv')
    return dbus.Dictionary({k:dbus.Dictionary(v,signature='sv') for k,v in profile.items()},signature='sa{sv}')

class Network:
    def __init__(self):
        self.bus=dbus.SystemBus(private=True)
        self.nm=dbus.Interface(self.bus.get_object(NM,ROOT),NM)
    def close(self):self.bus.close()
    def interface(self,path,name):return dbus.Interface(self.bus.get_object(NM,path),name)
    def props(self,path,name):return self.interface(path,PROPS).GetAll(name)
    def pending(self):
        try:data=json.loads(STATE.read_text())
        except (OSError,ValueError):return None
        if data['checkpoint'] not in [str(p) for p in self.props(ROOT,NM).get('Checkpoints',[])]:
            STATE.unlink(missing_ok=True);return None
        return data
    def save_pending(self,data):
        STATE.parent.mkdir(parents=True,exist_ok=True)
        temp=STATE.with_suffix('.tmp');temp.write_text(json.dumps(data));temp.chmod(0o600);temp.replace(STATE)
    def status(self):
        interfaces=[]
        primary=self.props(ROOT,NM).get('PrimaryConnection','/')
        for device in self.nm.GetDevices():
            prop=self.props(device,NM+'.Device');name=str(prop['Interface'])
            if name not in ('eth0','wlan0'):continue
            current={'interface':name,'kind':'wifi' if name=='wlan0' else 'ethernet','connected':int(prop['State'])==100,'state':int(prop['State']),'address':'','prefix':24,'gateway':'','dns':[],'mode':'dhcp','ssid':'','primary':False}
            active=prop.get('ActiveConnection','/')
            if active!='/':
                current['primary']=active==primary
                ap=self.props(active,NM+'.Connection.Active')
                settings=self.interface(ap['Connection'],NM+'.Settings.Connection').GetSettings()
                current['mode']='static' if settings.get('ipv4',{}).get('method')=='manual' else 'dhcp'
                ssid=settings.get('802-11-wireless',{}).get('ssid',[])
                current['ssid']=bytes(ssid).decode('utf-8',errors='replace')
            ipconfig=prop.get('Ip4Config','/')
            if ipconfig!='/':
                data=self.props(ipconfig,NM+'.IP4Config');addresses=data.get('AddressData',[])
                if addresses:current.update(address=str(addresses[0]['address']),prefix=int(addresses[0]['prefix']))
                current['gateway']=str(data.get('Gateway',''))
                current['dns']=[str(d['address']) for d in data.get('NameserverData',[]) if 'address' in d][:2]
            interfaces.append(current)
        pending=self.pending()
        temporary=read_temporary()
        return {'ok':True,'interfaces':interfaces,
                'pending':{'id':pending['id'],'interface':pending['interface'],'expires_at':pending['expires_at'],'temporary':pending.get('temporary',False)} if pending else None,
                'temporary_wifi':{k:temporary.get(k) for k in ('id','ssid','expires_at','disconnect_at')} if temporary else None,
                'temporary_subnet_conflict':bool(pending and pending.get('temporary') and overlapping_networks(interfaces))}
    def wifi(self):
        device=self.nm.GetDeviceByIpIface('wlan0');wifi=self.interface(device,NM+'.Device.Wireless')
        try:wifi.RequestScan(dbus.Dictionary({},signature='sv'))
        except dbus.DBusException:pass # Rate-limited scan still permits reading existing results.
        networks={}
        for path in wifi.GetAllAccessPoints():
            ap=self.props(path,NM+'.AccessPoint');ssid=bytes(ap['Ssid']).decode('utf-8',errors='replace')
            if not ssid:continue
            flags=int(ap.get('RsnFlags',0))
            security='sae' if flags & 0x400 and not flags & 0x100 else 'wpa-psk' if flags & 0x100 else 'unsupported'
            record={'ssid':ssid,'signal':int(ap['Strength']),'security':security}
            if ssid not in networks or record['signal']>networks[ssid]['signal']:networks[ssid]=record
        return {'ok':True,'networks':sorted(networks.values(),key=lambda n:-n['signal'])[:30]}
    def apply(self,payload):
        config=validate(payload)
        if read_temporary():raise NetworkError('Сначала отключите временный Wi-Fi установки')
        if self.pending():raise NetworkError('Подтвердите или отмените предыдущую настройку сети')
        if list(self.props(ROOT,NM).get('Checkpoints',[])):raise NetworkError('NetworkManager already has a pending checkpoint')
        device=self.nm.GetDeviceByIpIface(config['interface'])
        previous_connection='/'
        if config.get('temporary'):
            active=self.props(device,NM+'.Device').get('ActiveConnection','/')
            if active!='/':previous_connection=str(self.props(active,NM+'.Connection.Active')['Connection'])
        # A checkpoint belongs to this physical device, never Docker bridges.
        expires_at=time.time()+90
        checkpoint=self.nm.CheckpointCreate(dbus.Array([device],signature='o'),dbus.UInt32(90),dbus.UInt32(2))
        try:
            connection,active,_=self.nm.AddAndActivateConnection2(connection_settings(config),device,dbus.ObjectPath('/'),dbus.Dictionary({'persist':'memory'},signature='sv'))
            pending={'id':str(uuid.uuid4()),'checkpoint':str(checkpoint),'connection':str(connection),'active':str(active),'device':str(device),'interface':config['interface'],'expires_at':expires_at}
            if config.get('temporary'):
                pending.update(temporary=True,previous_connection=previous_connection,ssid=config['ssid'])
            self.save_pending(pending)
        except Exception:
            self.nm.CheckpointRollback(checkpoint)
            raise
        return self.status()
    def check_pending(self,payload):
        pending=self.pending()
        if not pending or payload.get('id')!=pending['id']:raise NetworkError('Настройка истекла или уже отменена. Обновите страницу.')
        return pending
    def confirm(self,payload):
        pending=self.check_pending(payload)
        if pending['expires_at']-time.time()<10:raise NetworkError('Время подтверждения истекло. Дождитесь отката и повторите.')
        prop=self.props(pending['device'],NM+'.Device')
        if int(prop['State'])!=100 or str(prop.get('ActiveConnection'))!=pending['active']:raise NetworkError('Новое подключение ещё не установлено')
        connection=self.interface(pending['connection'],NM+'.Settings.Connection')
        if pending.get('temporary'):
            status=self.status()
            if status['temporary_subnet_conflict']:
                self.rollback({'id':pending['id']})
                raise NetworkError('Подсеть телефона совпадает с Ethernet. Измените подсеть точки доступа или используйте офлайн-активацию.')
            wifi=next((i for i in status['interfaces'] if i['interface']=='wlan0'),{})
            if not wifi.get('address') or not wifi.get('gateway'):
                raise NetworkError('Дождитесь получения Wi-Fi адреса и шлюза')
            # AddAndActivateConnection2(persist=memory) already holds the PSK in
            # RAM. Never call GetSecrets/Update2 or enable autoconnect here.
            save_temporary({k:pending[k] for k in ('id','connection','active','device','previous_connection','ssid')} | {'expires_at':time.time()+7200})
            self.nm.CheckpointDestroy(pending['checkpoint'])
            STATE.unlink(missing_ok=True)
            return self.status()
        values=connection.GetSettings()
        if '802-11-wireless-security' in values:
            secrets=connection.GetSecrets('802-11-wireless-security')
            for key,secret in secrets.items():values[key].update(secret)
        values['connection']['autoconnect']=dbus.Boolean(True)
        values['connection']['autoconnect-priority']=dbus.Int32(999)
        connection.Update2(values,dbus.UInt32(1),dbus.Dictionary({},signature='sv'))
        self.nm.CheckpointDestroy(pending['checkpoint'])
        STATE.unlink(missing_ok=True)
        return self.status()
    def rollback(self,payload):
        pending=self.check_pending(payload)
        results=self.nm.CheckpointRollback(pending['checkpoint'])
        if any(int(result)!=0 for result in results.values()):raise NetworkError('Не все интерфейсы восстановлены')
        try:self.nm.CheckpointDestroy(pending['checkpoint'])
        except dbus.DBusException:pass
        STATE.unlink(missing_ok=True)
        return self.status()

    def temporary_connect(self,payload):
        # The caller cannot change Ethernet, routes or the retention duration.
        return self.apply({'interface':'wlan0','mode':'dhcp','temporary':True,
                           'ssid':payload.get('ssid',''),'password':payload.get('password',''),
                           'security':payload.get('security','wpa-psk')})

    def temporary_finish(self,payload):
        value=read_temporary()
        if not value:return {'ok':True,'scheduled':False}
        value['disconnect_at']=time.time()+30
        save_temporary(value)
        return {'ok':True,'scheduled':True,'disconnect_at':value['disconnect_at']}

    def temporary_disconnect(self,payload):
        pending=self.pending()
        if pending:
            if pending.get('temporary'):return self.rollback({'id':pending['id']})
            raise NetworkError('Сначала подтвердите или отмените настройку сети')
        value=read_temporary()
        if not value:return self.status()
        prop=self.props(value['device'],NM+'.Device')
        active=str(prop.get('ActiveConnection','/'))
        managed=active==value['active']
        if managed:self.nm.DeactivateConnection(value['active'])
        # Delete only our memory profile. Never delete saved Wi-Fi profiles.
        try:
            connection=self.interface(value['connection'],NM+'.Settings.Connection')
            if str(connection.GetSettings()['connection']['id'])!='LABRIX temporary setup internet':
                raise NetworkError('Временный профиль был изменён: требуется проверка установщика')
            connection.Delete()
        except dbus.DBusException as error:
            if 'UnknownConnection' not in error.get_dbus_name() and 'UnknownObject' not in error.get_dbus_name():raise
        TEMP.unlink(missing_ok=True)
        warning=''
        if (managed or active=='/') and value['previous_connection']!='/':
            try:self.nm.ActivateConnection(value['previous_connection'],value['device'],dbus.ObjectPath('/'))
            except dbus.DBusException:warning='Временный Wi-Fi удалён. Прежний Wi-Fi пока недоступен; проверьте состояние сети.'
        result=self.status()
        if warning:result['warning']=warning
        return result

def temporary_watchdog():
    while True:
        time.sleep(1)
        with ACTION_LOCK:
            value=read_temporary()
            if not value or min(value['expires_at'],value.get('disconnect_at',float('inf')))>time.time():continue
            network=None
            try:
                network=Network();network.temporary_disconnect({})
            except Exception:
                # Retry when NetworkManager is available; never persist PSKs.
                pass
            finally:
                if network:network.close()

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,status,data):
        body=json.dumps(data,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def handle_api(self,post=False):
        network=None
        try:
            action=self.path.strip('/')
            allowed=('apply','confirm','rollback','temporary-connect','temporary-disconnect','temporary-finish') if post else ('status','wifi')
            if action not in allowed:self.reply(404,{'detail':'Not found'});return
            network=Network()
            if post:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=8192:raise ValueError('Invalid body length')
                payload=json.loads(self.rfile.read(length))
                if not isinstance(payload,dict):raise ValueError('JSON object required')
                result=getattr(network,action.replace('-','_'))(payload)
            else:result=getattr(network,action)()
            self.reply(200,result)
        except (ValueError,TypeError) as e:self.reply(422,{'detail':str(e)})
        except NetworkError as e:self.reply(409,{'detail':str(e)})
        except Exception:self.reply(503,{'detail':'NetworkManager не выполнил запрос. Прежний профиль сохранён.'})
        finally:
            if network:network.close()
    def do_GET(self):
        with ACTION_LOCK:self.handle_api()
    def do_POST(self):
        with ACTION_LOCK:self.handle_api(True)

if __name__=='__main__':
    Path(SOCKET).parent.mkdir(parents=True,exist_ok=True)
    Path(SOCKET).unlink(missing_ok=True)
    server=UnixStreamServer(SOCKET,Handler);os.chmod(SOCKET,0o600)
    threading.Thread(target=temporary_watchdog,name='temporary-wifi-cleanup',daemon=True).start()
    server.serve_forever()
