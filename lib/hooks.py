import re
import os
import sys
import shutil
import subprocess

sys.path.insert(0, os.path.join(os.environ['CHARM_DIR'], 'lib'))

from charmhelpers.core import (
    hookenv,
    host,
)

from charmhelpers import fetch
from helpers import apache2
from helpers.host import touch, extract_tar


config = hookenv.config()


def install():
    hookenv.log('Installing benchmark-gui')
    fetch.apt_update()
    fetch.apt_install(fetch.filter_installed_packages(['graphite-carbon',
                                                       'graphite-web',
                                                       'apache2',
                                                       'apache2-mpm-worker',
                                                       'libapache2-mod-wsgi',
                                                       'postgresql',
                                                       'python-virtualenv',
                                                       'python-dev',
                                                       'python-requests',
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
    subprocess.check_call(['make', '.venv'], cwd='/opt/collector-web')

    extract_tar('payload/collector-worker.tar.gz', '/opt/collector-worker')
    subprocess.check_call(['make', '.venv'], cwd='/opt/collector-worker')

    # setup postgres for collector-web
    subprocess.check_call(
        'sudo -u postgres psql -c "CREATE USER cabs WITH UNENCRYPTED PASSWORD \'cabs\';"',
        shell=True)
    subprocess.check_call(
        'sudo -u postgres psql -c "CREATE DATABASE cabs WITH OWNER cabs;"',
        shell=True)
    subprocess.check_call(
        '.venv/bin/initialize_db production.ini'.split(),
        cwd='/opt/collector-worker')

    # Install upstart config for collector-web
    shutil.copyfile('/opt/collector-web/conf/upstart/collectorweb.conf',
                    '/etc/init/collectorweb.conf')

    host.chownr('/opt/collector-web', 'ubuntu', 'ubuntu')

    host.service_restart('apache2')
    host.service_restart('carbon-cache')
    host.service_restart('collectorweb')

    # Install cron, vhost for gui, etc
    hookenv.open_port(9000)
    hookenv.open_port(9001)
    hookenv.open_port(2003)


def configure(force=False):
    with open('/etc/graphite/local_settings.py', 'r+') as f:
        contents = f.read()
        contents = re.sub(r'#TIME_ZONE = .*', "TIME_ZONE = 'Etc/UTC'",
                          contents)
        f.seek(0, 0)
        f.truncate()
        f.write(contents)

    if config.changed('debug'):
        if not config.get('debug', False):
            address = '127.0.0.1'
        else:
            address = '0.0.0.0'

        with open('/etc/redis/redis.conf', 'r+') as f:
            cfg = f.read()
            cfg = re.sub(r'bind .*', 'bind %s' % address, cfg)
            f.seek(0, 0)
            f.truncate()
            f.write(cfg)

        host.service_restart('redis-server')

    if 'juju-secret' not in config:
        return

    if config.changed('juju-user') or config.changed('juju-secret') or force:
        api_addresses = os.getenv('JUJU_API_ADDRESSES')
        if api_addresses is not None:
            juju_api = 'wss://%s' % api_addresses.split()[0]

        graphite_url = 'http://%s:9001' % hookenv.unit_get('public-address')

        with open('/opt/collector-web/production.ini', 'r+') as f:
            ini = f.read()
            ini = re.sub(r'juju.api.user = .*',
                         'juju.api.user = %s' % config['juju-user'], ini)
            ini = re.sub(r'juju.api.secret = .*',
                         'juju.api.secret = %s' % config['juju-secret'], ini)
            ini = re.sub(r'juju.api.endpoint = .*',
                         'juju.api.endpoint = %s' % juju_api, ini)
            ini = re.sub(r'graphite.url = .*',
                         'graphite.url = %s' % graphite_url, ini)

            f.seek(0, 0)
            f.truncate()
            f.write(ini)

        host.service_restart('collectorweb')


def benchmark():
    if hookenv.in_relation_hook():
        import json
        import requests
        benchmarks = hookenv.relation_get('benchmarks')
        if benchmarks:
            hookenv.log('benchmarks received: %s' % benchmarks)
            service = hookenv.remote_unit().split('/')[0]
            payload = {'benchmarks': [b for b in benchmarks.split(',')]}
            r = requests.post('http://localhost:9000/api/services/%s' % service,
                              data=json.dumps(payload),
                              headers={'content-type': 'application/json'})

        graphite_url = 'http://%s:9001' % hookenv.unit_get('public-address')

        hookenv.relation_set(hostname=hookenv.unit_private_ip(),
                             port=2003, graphite_port=9001,
                             graphite_endpoint=graphite_url, api_port=9000)


def emitter_rel():
    if hookenv.in_relation_hook():
        hookenv.relation_set(hostname=hookenv.unit_private_ip(), port=2003,
                             api_port=9000)


def start():
    host.service_reload('apache2')
    host.service_restart('collectorweb')


def stop():
    apache2.disable_site('cabs-graphite')
    os.remove('/etc/apache2/sites-available/cabs-graphite.conf')
    host.service_reload('apache2')
    host.service_stop('carbon-cache')
    host.service_stop('collectorweb')
