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
from helpers.host import touch


def install():
    hookenv.log('Installing benchmark-guii')
    fetch.apt_update()
    fetch.apt_install(fetch.filter_installed_packages(['graphite-carbon',
                                                       'graphite-web',
                                                       'apache2',
                                                       'apache2-mpm-worker',
                                                       'libapache2-mod-wsgi']))
    touch('/etc/apache2/sites-available/cabs-graphite.conf')
    shutil.copyfile('files/graphite.conf',
                    '/etc/apache2/sites-available/cabs-graphite.conf')
    shutil.copyfile('files/graphite-carbon', '/etc/default/graphite-carbon')
    apache2.enable_site('cabs-graphite')

    host.chownr('/var/lib/graphite', '_graphite', '_graphite')
    subprocess.check_call('sudo -u _graphite graphite-manage syncdb --noinput',
                          shell=True)

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

