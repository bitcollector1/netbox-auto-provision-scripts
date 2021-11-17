"""
Seed Script to add minios systems to netbox to be provisioned.

1. Adds all minios systems that have an IP from ARP
2. Script outputs IP and MINIOS so you can paste into /etc/hosts so script knows IP for SSH
"""

import os
import sys
import requests
import pynetbox
import warnings

from nornir import InitNornir
from nornir_utils.plugins.functions import print_result
from nornir_napalm.plugins.tasks import napalm_get
from nornir.core.filter import F
from nornir.core.task import Task, Result
from urllib3.exceptions import InsecureRequestWarning

warnings.filterwarnings('ignore')

session = requests.Session()
session.verify = False

nb = pynetbox.api(os.getenv('NB_URL'), os.getenv('NB_TOKEN'))
nb.http_session = session

nr = InitNornir(config_file="../inventory/nornir_nb_layer-3.yaml")

nr.inventory.defaults.username = input("Enter Username: ")
nr.inventory.defaults.password = input("Enter Password: ")

# User variables
domain_extension = '.local.domain'
switch = 'switch-name'
rack_name = '0102'

nr = nr.filter(F(name__contains=switch))
nr.inventory.hosts

lldp_neighbors = nr.run(task=napalm_get, getters=["get_lldp_neighbors_detail"])
interfaces = lldp_neighbors[switch][0].result['get_lldp_neighbors_detail']

arp_table = nr.run(task=napalm_get, getters=["get_arp_table"])


def add_minios(task: Task, minios_system, ip, eth) -> Result:
    """
    Send commands using netmiko to update the server info .
    Seed file for the real provision script
    """
    if not nb.dcim.racks.get(name=rack_name):
        print(f"Rack Name: {rack_name} is not valid, exiting")
        sys.exit()

    device = nb.dcim.devices.get(name=task.host.name)

    try:

        system = nb.dcim.devices.create({'name': minios_system, 'device_role': {'name': 'minios'},
                                         'device_type': {'model': 'SYS-6029TP-H-EI012'}, 'status': 'staged', 'rack': {'name': rack_name},
                                         'site': {'name': '1103 Platform Engineering Lab'}, 'platform': {'name': 'linux'},
                                         'tenant': '1'})

        print(f"{ip}  {system} ")

    except:
        pass

for k in interfaces.keys():
    remote_port = interfaces[k][0]['remote_port']
    remote_port_description = interfaces[k][0]['remote_port_description']
    remote_system = interfaces[k][0]['remote_system_name']

    if remote_system is not None:
        if 'node' in remote_system:
            remote_system = remote_system.replace(domain_extension, " ")

            for i in arp_table:
                arps = arp_table[i][0].result['get_arp_table']

                j = 0

                for a in arps:
                    interface = arps[j]['interface']

                    if k in interface:
                        address = arps[j]['ip']
                        nr.run(task=add_minios, minios_system=remote_system, ip=address, eth=remote_port_description)
                    j += 1
