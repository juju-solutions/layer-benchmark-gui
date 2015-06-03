# Overview

The CABS charm collects metrics from benchmark runs across an environment and allows you to compare the results.

# Usage

Because CABS needs to communicate with the Juju API server, it will need the `admin-secret` from `~/.juju/environment.yaml`.

    juju deploy cabs
    juju set cabs juju-secret=<admin-secret>

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

To collect performance metrics about the system(s) being benchmarked, you'll need to install the subordinate `cabs-collector` charm. This charm will collect statistics such as disk i/o, memory usage, and even installed package state, back to `cabs`.

    juju deploy cabs-collector
    juju add-relation cabs-collector:collector cabs:collector
    juju add-relation cabs-collector mediawiki
    juju add-relation cabs-collector mysql
