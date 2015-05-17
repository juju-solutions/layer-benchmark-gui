# Overview

The benchmark-gui charm collects metrics from benchmark runs across an environment and allows you to compare the results.

# Usage

Because the benchmark-gui needs to communicate with the Juju API server, it will need the `admin-secret` from `~/.juju/environment.yaml`.

    juju deploy benchmark-gui
    juju set benchmark-gui juju-secret=<admin-secret>

You can then browse to http://ip-address:9000/ to view and compare the benchmark metrics.

# Collecting benchmark data

In order to collate data, a benchmark-enabled charm must support the `benchmark` relation.

    juju deploy siege
    juju deploy mysql
    juju deploy mediawiki
    juju add-relation mysql:db mediawiki:db
    juju add-relation mediawiki:website siege:website
    juju add-relation siege:benchmark benchmark-gui:benchmark
    juju action do siege/0 siege

# Collecting performance metrics

To collect performance metrics about the system(s) being benchmarked, you'll need to install the subordinate `collectd` charm. This charm will collect statistics such as disk i/o, memory usage, and even installed package state, back to `benchmark-gui`.

    juju deploy collectd
    juju add-relation collectd:collector benchmark-gui:collector
    juju add-relation collectd mediawiki
    juju add-relation collectd mysql
