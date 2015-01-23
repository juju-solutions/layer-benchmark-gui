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
    hookenv.log('Installing benchmark-guii')
    fetch.apt_update()
    fetch.apt_install(fetch.filter_installed_packages(['graphite-carbon',
                                                       'graphite-web',
                                                       'apache2',
                                                       'apache2-mpm-worker',
                                                       'libapache2-mod-wsgi',
                                                       'python-virtualenv',
                                                       'redis-server']))
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

    with open('/opt/collector-web/conf/apache/app.conf', 'r+') as f:
        conf = f.read()

        conf = "Listen 9000" + '\n' + conf
        conf = conf.replace('<VirtualHost *:80>', '<VirtualHost *:9000>', conf)
        conf = conf.replace('/path/to/app/venv/dir',
                            '/opt/collector-web/.venv', conf)
        conf = conf.replace('/path/to/dir/containing/wsgi/file',
                            '/opt/collector-web/conf/apache', conf)

        with open('/etc/apache2/sites-available/cabs-collector-web.conf',
                  'w') as a:
            a.write(conf)

    with open('/opt/collector-web/conf/apache/app.wsgi', 'r+') as f:
        conf = f.read()

        conf = conf.replace("ini_path = '/path/to/myapp/production.ini'",
                            "ini_path = '/opt/collector-web/production.ini'")
        conf = conf.replace('<VirtualHost *:80>', '<VirtualHost *:9000>', conf)
        conf = conf.replace('/path/to/app/venv/dir',
                            '/opt/collector-web/.venv', conf)
        conf = conf.replace('/path/to/dir/containing/wsgi/file',
                            '/opt/collector-web/conf/apache', conf)
        f.seek(0, 0)
        f.write(conf)

    host.chownr('/opt/collector-web', 'ubuntu', 'ubuntu')
    apache2.enable_site('cabs-collector-web')

    host.service_restart('apache2')
    host.service_restart('carbon-cache')

    # Install cron, vhost for gui, etc
    hookenv.open_port(9000)
    hookenv.open_port(9001)
    hookenv.open_port(2003)


def configure():
    with open('/etc/graphite/local_settings.py', 'r+') as f:
        contents = f.read()
        contents = re.sub(r'#TIME_ZONE = .*', "TIME_ZONE = 'Etc/UTC'",
                          contents)
        f.seek(0, 0)
        f.write(new_contents)

    if config.changed('juju-user') or config.changed('juju-secret'):
        with open('/opt/collector-web/production.ini', 'r+') as f:
            ini = f.read()
            ini = re.sub(r'juju.api.user = .*',
                         'juju.api.user = %s' % config['juju-user'], ini)
            ini = re.sub(r'juju.api.secret = .*',
                         'juju.api.secret = %s' % config['juju-secret'], ini)
            f.seek(0, 0)
            f.write(ini)


def emitter_rel():
    if hookenv.in_relation_hook():
        hookenv.relation_set(hostname=hookenv.unit_private_ip(), port=2003)


def start():
    host.service_reload('apache2')


def stop():
    apache2.disable_site('cabs-graphite')
    os.remove('/etc/apache2/sites-available/cabs-graphite.conf')
    host.service_reload('apache2')
    host.service_stop('carbon-cache')
