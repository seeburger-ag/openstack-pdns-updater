#!/usr/bin/env python

# OpenStack PDNS Updater listens on the RabbitMQ message bus. Whenever an
# instance is created or deleted DNS updater creates or removes
# its DNS A record. 

import json
import logging as log
import sys
import os
import powerdns

from kombu import BrokerConnection, Exchange, Queue
from kombu.mixins import ConsumerMixin
from keystoneauth1 import session
from keystoneauth1.identity import v3
from novaclient import client


LOG_FILE=os.getenv('LOG_FILE','openstack-pdns-updater.log')

EXCHANGE_NAME_NOVA=os.getenv('EXCHANGE_NAME_NOVA','nova')
EXCHANGE_NAME_NEUTRON=os.getenv('EXCHANGE_NAME_NEUTRON','neutron')
ROUTING_KEY=os.getenv('ROUTING_KEY','notifications.info')
QUEUE_NAME=os.getenv('QUEUE_NAME','pdns_updater_queue')
BROKER_URI=os.getenv('BROKER_URI','UNDEFINED')

OS_IDENTITY_API_VERSION=os.getenv('OS_IDENTITY_API_VERSION','3')
OS_AUTH_URL=os.getenv('OS_AUTH_URL','UNDEFINED')
OS_USERNAME=os.getenv('OS_USERNAME','UNDEFINED')
OS_PASSWORD=os.getenv('OS_PASSWORD','UNDEFINED')
OS_PROJECT_NAME=os.getenv('OS_PROJECT_NAME','UNDEFINED')
OS_USER_DOMAIN_NAME=os.getenv('OS_USER_DOMAIN_NAME','Default')
OS_PROJECT_DOMAIN_NAME=os.getenv('OS_PROJECT_DOMAIN_NAME','Default')
OS_INTERFACE=os.getenv('OS_INTERFACE','public')
OS_CACERT=os.getenv('OS_CACERT', '/opt/openstack-pdns-updater/ca-certificates.crt')

EVENT_CREATE=os.getenv('EVENT_CREATE','compute.instance.create.end')
EVENT_DELETE=os.getenv('EVENT_DELETE','compute.instance.delete.start')
EVENT_IP_UPDATE=os.getenv('EVENT_IP_UPDATE','floatingip.update.end')

INTERNAL_DOMAIN=os.getenv('INTERNAL_DOMAIN','UNDEFINED')
EXTERNAL_DOMAIN=os.getenv('EXTERNAL_DOMAIN','UNDEFINED')

PDNS_API=os.getenv('PDNS_API','UNDEFINED')
PDNS_KEY=os.getenv('PDNS_KEY','UNDEFINED')
TTL=os.getenv('TTL','60')
SKIP_DELETE=os.getenv('SKIP_DELETE','false').lower() in ("true", "yes", "1")


log.basicConfig(level=log.INFO, format='%(asctime)s %(message)s', handlers=[log.FileHandler(LOG_FILE), log.StreamHandler()])

class DnsUpdater(ConsumerMixin):

    def __init__(self, connection):
        self.connection = connection
        auth = v3.Password(auth_url=OS_AUTH_URL,
                           username=OS_USERNAME,
                           password=OS_PASSWORD,
                           project_name=OS_PROJECT_NAME,
                           user_domain_name=OS_USER_DOMAIN_NAME,
                           project_domain_name=OS_PROJECT_DOMAIN_NAME)
        s = session.Session(auth=auth, verify=OS_CACERT)
        log.info("Session {}".format(s))
        self.nova = client.Client(session=s, version=2)
        return

    def get_server_for_ip(self, ip, project_id):
        for server in self.nova.servers.list(search_opts={'all_tenants':1}):
            if server.tenant_id != project_id:
                log.debug("Server tenant doesn't match. Continue...")
                continue
            
            for net, addresses in server.networks.items():
                for a in addresses:
                    if ip == a:
                        return server
        return ""

    def get_consumers(self, consumer, channel):
        exchange_nova = Exchange(EXCHANGE_NAME_NOVA, type="topic", durable=False)
        exchange_neutron = Exchange(EXCHANGE_NAME_NEUTRON, type="topic", durable=False)
        queue_nova = Queue(QUEUE_NAME, exchange_nova, routing_key = ROUTING_KEY, durable=False, auto_delete=True, no_ack=True)
        queue_neutron = Queue(QUEUE_NAME, exchange_neutron, routing_key = ROUTING_KEY, durable=False, auto_delete=True, no_ack=True)
        return [ consumer( queues = [queue_neutron], callbacks = [ self.on_message ]) ,  consumer(queue_nova, callbacks = [ self.on_message ])]

    def on_message(self, body, message):
        try:
            self._handle_message(body)
        except Exception as e:
            log.info(repr(e))

    def _handle_message(self, body):

        jbody = json.loads(body["oslo.message"])
        event_type = jbody["event_type"]
        log.info("Event type: {}".format(event_type))
        project = jbody["_context_project_name"]
        project_id = jbody["_context_project_id"]
        hostaddr_internal = ""

        if event_type in [ EVENT_CREATE, EVENT_DELETE, EVENT_IP_UPDATE ]:

            log.info("Have changes for project {}".format(project))

            api_client = powerdns.PDNSApiClient(api_endpoint=PDNS_API, api_key=PDNS_KEY)
            api = powerdns.PDNSEndpoint(api_client)

            internal_zone = api.servers[0].get_zone('{}.internal.dev.seeburger.de.'.format(project))
            external_zone = api.servers[0].get_zone('{}.dev.seeburger.de.'.format(project))

            if event_type == EVENT_CREATE:
                server_id = jbody["payload"]["instance_id"]
                hostname = jbody["payload"]["hostname"]
                hostaddr = jbody["payload"]["fixed_ips"][0]["address"]
                log.info("Adding {}.{}.internal.seeburger.de. \tA \t{} \t{}".format(hostname, project, TTL, hostaddr))

                user = jbody["_context_user_name"]
                user_id = jbody["_context_user_id"]
                # server_id = jbody["payload"]["instance_id"]
                log.debug("Instance ID: {}, User: {}, User ID: {}, Project: {}, Project ID: {}".format(server_id, user, user_id, project, project_id))

                server = self.nova.servers.get(server_id)

                try:
                    self.nova.servers.set_meta_item(server, "project", project)
                    self.nova.servers.set_meta_item(server, "project_id", project_id)
                    self.nova.servers.set_meta_item(server, "user", user)
                    self.nova.servers.set_meta_item(server, "user_id", user_id)
                    self.nova.servers.set_meta_item(server, "ip", hostaddr)
                    self.nova.servers.set_meta_item(server, "hostname", hostname)
                except Exception as e:
                    log.warn("Exception {} thrown".format(e))

                # Delete old A records, which may have existed and create a new one in the
                # Zone of the internal and externat domain
                internal_zone.delete_record([powerdns.RRSet(hostname,'A',[])])
                external_zone.delete_record([powerdns.RRSet(hostname,'A',[])])
                internal_zone.create_records([
                    powerdns.RRSet(hostname,'A',[(hostaddr,False)], TTL)
                    ])

            elif event_type == EVENT_DELETE and SKIP_DELETE:
                log.info("Delete request received, but SKIP_DELETE is set to {}, so skipping".format(SKIP_DELETE))
                
            elif event_type == EVENT_DELETE and not SKIP_DELETE:
                server_id = jbody["payload"]["instance_id"]
                hostname = jbody["payload"]["hostname"]
                hostaddr = ""
                log.info("Deleting {}.{}[.internal].seeburger.de".format(hostname, project))

                # As the instance vanished, delete all remaining know A records.
                internal_zone.delete_record([powerdns.RRSet(hostname,'A',[])])
                external_zone.delete_record([powerdns.RRSet(hostname,'A',[])])

            elif event_type == EVENT_IP_UPDATE:
                hostaddr = jbody["payload"]["floatingip"]["floating_ip_address"]
                ip = jbody["payload"]["floatingip"]["fixed_ip_address"]
                log.info("Hostaddr {}".format(hostaddr))
                log.info("Ip {}".format(ip))
                if ip == None:
                    log.info("Disaccotiated floating ip {}. Do nothing for now...".format(hostaddr))
                    return

                if not hostaddr.isspace():
                    server = self.get_server_for_ip(ip, project_id)
                    hostaddr_internal = ip
                    hostname = server.name
                    #nsupdate_script = NSUPDATE_ADD_PUBLIC
                    log.info("Adding records for hostname {}".format(hostname))
                    
                    # Add or update A records fir internal and external domain.
                    log.info("Adding address...")
                    external_zone.create_records([
                        powerdns.RRSet(hostname, 'A', [(hostaddr, False)], TTL)
                        ])
                    internal_zone.create_records([
                        powerdns.RRSet(hostname, 'A', [(hostaddr_internal, False)], TTL)
                        ])

                log.info("Added {}.{}.dev.seeburger.de {}".format(hostname, project, hostaddr))
            else:
                log.error("Unknown event type: {} - Do nothing".format(event_type))
                return

if __name__ == "__main__":
    log.info("Connecting to broker {}".format(BROKER_URI))
    with BrokerConnection(BROKER_URI, heartbeat=4) as connection:
        DnsUpdater(connection).run()

# vim: expandtab sw=4 ts=4
