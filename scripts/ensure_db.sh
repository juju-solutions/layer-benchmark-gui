#!/bin/bash

# Create cabs database if it doesn't exist

PSQL='sudo -u postgres psql'

if ! $PSQL -l | grep cabs >/dev/null 2>&1 ; then
  $PSQL -c "CREATE DATABASE cabs WITH OWNER cabs;"
else
  juju-log "Database 'cabs' already exists, skipping creation."
fi
