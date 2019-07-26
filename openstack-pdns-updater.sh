#!/bin/bash

[ -f /opt/openstack-pdns-updater/environment ] && source /opt/openstack-pdns-updater/environment
python3 /opt/openstack-pdns-updater/openstack-pdns-updater.py
