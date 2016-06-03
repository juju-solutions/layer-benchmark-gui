import json
import re
import os
import sys
import shutil
import logging
import subprocess
import requests

from charms.reactive import when, when_not, set_state, hook
from charmhelpers.core import (
    hookenv,
    host,
    unitdata,
)

from charmhelpers import fetch
from helpers import apache2
from helpers.host import touch, extract_tar

#TODO: use reactive states instead of hooks
#TODO: use templates instead of ./files

@hook('install')
def install_benchmark_gui():
    hookenv.status_set('maintenance', 'Installing CABS')
    fetch.apt_update()
    fetch.apt_install(fetch.filter_installed_packages([
        'graphite-carbon',
        'graphite-web',
        'apache2',
        'apache2-mpm-worker',
        'libapache2-mod-wsgi',
        'postgresql',
        'python-virtualenv',
        'python-dev',
    ]))

    touch('/etc/apache2/sites-available/cabs-graphite.conf')
    shutil.copyfile('files/graphite.conf',
                    '/etc/apache2/sites-available/cabs-graphite.conf')
    shutil.copyfile('files/graphite-carbon', '/etc/default/graphite-carbon')
    apache2.enable_site('cabs-graphite')

    host.chownr('/var/lib/graphite', '_graphite', '_graphite')
    subprocess.check_call('sudo -u _graphite graphite-manage syncdb --noinput',
                          shell=True)

    extract_tar('payload/collector-web.tar.gz', '/opt/collector-web')
    config = hookenv.config()
    try:
        env = None
        if config.get('proxy'):
            env = dict(os.environ)
            env.update({'http_proxy': config.get('proxy'),
                        'https_proxy': config.get('proxy')})
        subprocess.check_call(['make', '.venv'], cwd='/opt/collector-web',
                              env=env)
    except subprocess.CalledProcessError as e:
        logging.exception(e)
        hookenv.status_set(
            'blocked', 'Failed to create venv - do you require a proxy?')
        return

    # setup postgres for collector-web
    subprocess.check_call(['scripts/ensure_db_user.sh'])
    subprocess.check_call(['scripts/ensure_db.sh'])

    # Install upstart config for collector-web
    shutil.copyfile('/opt/collector-web/conf/upstart/collectorweb.conf',
                    '/etc/init/collectorweb.conf')

    host.chownr('/opt/collector-web', 'ubuntu', 'ubuntu')

    host.service_restart('apache2')
    host.service_restart('carbon-cache')
    restart_collectorweb()

    # Install cron, vhost for gui, etc
    hookenv.open_port(9000)
    hookenv.open_port(9001)
    hookenv.open_port(2003)


@hook('config-changed')
def configure(force=False):
    config = hookenv.config()

    def changed(key):
        return force or config.changed(key)

    if config.changed('proxy') and config.get('proxy'):
        shutil.rmtree('/opt/collector-web')
        install_benchmark_gui()
        if hookenv.status_get() == 'blocked':
            return  # We're blocked again

    with open('/etc/graphite/local_settings.py', 'r+') as f:
        contents = f.read()
        contents = re.sub(r'#TIME_ZONE = .*', "TIME_ZONE = 'Etc/UTC'",
                          contents)
        f.seek(0, 0)
        f.truncate()
        f.write(contents)

    #TODO Setting the juju-secret _after_ adding a relation to a target service
    #     is crashtastic. Fixme.
    if 'juju-secret' not in config:
        return

    ini_path = '/opt/collector-web/production.ini'
    with open(ini_path, 'r') as f:
        ini = f.read()

    api_addresses = os.getenv('JUJU_API_ADDRESSES')
    if api_addresses:
        if 'JUJU_ENV_UUID' in os.environ:
            # juju 1.x
            typ = 'environment'
            uuid = os.environ['JUJU_ENV_UUID']
        else:
            # juju 2.x +
            typ = 'model'
            uuid = os.environ['JUJU_MODEL_UUID']

        juju_api = 'wss://{server}/{typ}/{uuid}/api'.format(
            server=api_addresses.split()[0],
            typ=typ,
            uuid=uuid,
        )
        ini = re.sub(r'juju.api.endpoint =.*',
                     'juju.api.endpoint = %s' % juju_api, ini)

    ini = re.sub(
        r'graphite.url =.*',
        'graphite.url = http://%s:9001' % hookenv.unit_get('public-address'),
        ini)

    if changed('juju-user'):
        ini = re.sub(
            r'juju.api.user =.*',
            'juju.api.user = %s' % config.get('juju-user') or '', ini)

    if changed('juju-secret'):
        ini = re.sub(
            r'juju.api.secret =.*',
            'juju.api.secret = %s' % config.get('juju-secret') or '', ini)

    if changed('publish-url'):
        ini = re.sub(
            r'publish.url =.*',
            'publish.url = %s' % config.get('publish-url') or '', ini)

    with open(ini_path, 'w') as f:
        f.write(ini)

    restart_collectorweb()
    hookenv.status_set('active',
                       'Ready http://%s:9000' % hookenv.unit_public_ip())


def set_action_id(action_id):
    if unitdata.kv().get('action_id') == action_id:
        # We've already seen this action_id
        return

    unitdata.kv().set('action_id', action_id)

    if not action_id:
        return

    # Broadcast action_id to collectors
    for rid in hookenv.relation_ids('collector'):
        hookenv.relation_set(relation_id=rid, relation_settings={
            'action_id': action_id
        })


def set_benchmark_actions(rid, unit):
    """Tell collectorweb which actions are benchmarks for the relation
    defined by this rid and unit.

    """
    benchmarks = hookenv.relation_get('benchmarks', unit=unit, rid=rid)
    if benchmarks:
        service = unit.split('/')[0]
        payload = {'benchmarks': [b for b in benchmarks.split(',')]}
        hookenv.log(
            'Setting benchmarks for {}: {}'.format(
                service, payload['benchmarks']))
        requests.post(
            'http://localhost:9000/api/services/{}'.format(service),
            data=json.dumps(payload),
            headers={
                'content-type': 'application/json'
            }
        )


@when('benchmark.registered')
def benchmark_registered(benchmark):
    if not hookenv.in_relation_hook():
        return

    set_action_id(hookenv.relation_get('action_id'))

    if host.service_running('collectorweb'):
        set_benchmark_actions(hookenv.relation_id(), hookenv.remote_unit())

    graphite_url = 'http://%s:9001' % hookenv.unit_get('public-address')

    hookenv.relation_set(hostname=hookenv.unit_private_ip(),
                         port=2003, graphite_port=9001,
                         graphite_endpoint=graphite_url, api_port=9000)


@when('collector.connected')
def emitter_rel(collector):
    if hookenv.in_relation_hook():
        hookenv.relation_set(hostname=hookenv.unit_private_ip(), port=2003,
                             api_port=9000)


def restart_collectorweb():
    """Restart collectorweb tell it which actions are benchmarks
    for each service on the 'benchmark' relation. This ensures that
    collectorweb has the latest data from the relation, even if it
    wasn't running when the relation hooks were fired.

    """
    host.service_restart('collectorweb')
    for rid in hookenv.relation_ids('benchmark'):
        for unit in hookenv.related_units(rid):
            set_benchmark_actions(rid, unit)


@hook('start')
def start():
    host.service_reload('apache2')
    restart_collectorweb()


@hook('stop')
def stop():
    apache2.disable_site('cabs-graphite')
    os.remove('/etc/apache2/sites-available/cabs-graphite.conf')
    host.service_reload('apache2')
    host.service_stop('carbon-cache')
    host.service_stop('collectorweb')


@hook('upgrade-charm')
def upgrade():
    shutil.rmtree('/opt/collector-web')
    install_benchmark_gui()
    configure(True)
    start()
