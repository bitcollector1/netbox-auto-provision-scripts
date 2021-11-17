"""
Script to update a server/minios details in NetBox.

1. System needs to exist in netbox before you can update the details --> run the seed script if needed.
2. LLDP needs to be enabled on the host for this script to properly make the network connections.
3. Adjusted for serial processing due to random issues with the threads.
"""
import os
import sys
import warnings
import requests
import pynetbox

from netaddr import IPAddress
from nornir import InitNornir
from nornir.core.task import Task, Result
from nornir_napalm.plugins.tasks import napalm_get
from nornir_netmiko.tasks import netmiko_send_command
from urllib3.exceptions import InsecureRequestWarning

warnings.filterwarnings('ignore')

session = requests.Session()
session.verify = False

nb = pynetbox.api(os.getenv('NB_URL'), os.getenv('NB_TOKEN'))
nb.http_session = session

nr = InitNornir(config_file="../inventory/nornir_nb_minios.yaml")

nr.inventory.defaults.username = input("Enter Username: ")
nr.inventory.defaults.password = input("Enter Password: ")
host = nr.inventory.hosts

# Works one rack at a time currently
rack_name = '0102'

# Set device role for finished state
device_role_name = 'server'

# Print host list to the screen for a sanity check
print(host)


def update_server(task: Task) -> Result:
    """
    Send commands using netmiko to update the server info .

    Create Manufacturer and Product if it does not already exist
    Update Manufacturer, Product, Serial, Asset_Tag, OS_Version
    """
    if not nb.dcim.racks.get(name=rack_name):
        print(f"Rack Name: {rack_name} is not valid, exiting!")
        sys.exit()

    if not nb.dcim.device_roles.get(name=device_role_name):
        print(f"Device Role: {device_role_name} is not valid, exiting!")
        sys.exit()

    system_manufacturer = task.run(netmiko_send_command, command_string="sudo dmidecode -s system-manufacturer")
    manufacturer = system_manufacturer[0].result.lower()

    if 'dell' in manufacturer:
        manufacturer = 'dell'

    if 'Quanta' in manufacturer:
        manufacturer = 'qct'

    slug_vendor = manufacturer.lower().replace(" ", "-")

    try:
        if nb.dcim.manufacturers.get(name=manufacturer) is None:
            nb.dcim.manufacturers.create(name=manufacturer, slug=slug_vendor)
    except:
        print(f"Error Creating the manufacturer {manufacturer} in NetBox")

    system_product_name = task.run(netmiko_send_command, command_string="sudo dmidecode -s system-product-name")
    device_type = system_product_name[0].result

    slug_name = device_type.lower().replace(" ", "-")

    # All devices provisioned through this script should be a child (server) that will go into a parent (chassis)
    try:
        if nb.dcim.device_types.get(model=device_type) is None:
            nb.dcim.device_types.create(model=device_type, slug=slug_name, manufacturer={'name': manufacturer}, u_height=0, subdevice_role='child')
    except:
        print(f"Error Creating {device_types} in NetBox")

    system_serial_number = task.run(netmiko_send_command, command_string="sudo dmidecode -s system-serial-number")
    serial = system_serial_number[0].result

    if nb.dcim.devices.filter(serial):
        print(f"{serial} is already in NetBox!")
        sys.exit()

    baseboard_asset_tag = task.run(netmiko_send_command, command_string="sudo dmidecode -s baseboard-asset-tag")
    baseboard_asset = baseboard_asset_tag[0].result

    chassis_asset_tag = task.run(netmiko_send_command, command_string="sudo dmidecode -s  chassis-asset-tag")
    chassis_asset = chassis_asset_tag[0].result

    if baseboard_asset.isdigit():
        asset = baseboard_asset

    elif chassis_asset.isdigit():
        asset = chassis_asset

    else:
        asset = None
        print(f" Asset Tags are invalid, setting to None --> Baseboard:{baseboard_asset}  Chassis:{chassis_asset} ")

    if asset is not None:
        if nb.dcim.devices.get(asset_tag=asset):
            print(f"Asset Tag: {asset} already exists in Netbox!!")
            sys.exit()

    release = task.run(netmiko_send_command, command_string="cat /etc/*release* | grep PRETTY_NAME")
    os_ver = release[0].result.split("=")[-1].replace("(Core)", "").strip('"').strip()

    slug_os_name = os_ver.lower().replace(" ", "-")

    try:
        if not nb.extras.tags.get(name=os_ver):
            nb.extras.tags.create({'name': os_ver, 'slug': slug_os_name, 'color': '808080'})
    except:
        print(f" Could not create the tag for{os_ver}")

    # call a device object and then use that object to update a device
    device = nb.dcim.devices.get(name=task.host.name)

    try:
        device.update({'name': device.name, 'device_role': {'name': device_role_name}, 'device_type': {'model': device_type},
                       'status': 'active', 'site': {'name': '1103 Platform Engineering Lab'}, 'rack_name': rack_name,
                       'serial': serial, 'asset_tag': asset, 'platform': {'name': 'linux'},
                       'tenant': '1', 'tags': [{'name': os_ver}]})

        print(f"Successfully updated Device:{device.name}")

    except:
        print(f"Error updating the device info {device.name} {device_type} {asset} {rack_name}")


def create_interface(task: Task) -> Result:
    """
    Create Interface, Add IP and Connect to host interface to switch interface.

    LLDP Needs to be enabled on the switch AND the host for the connection to be made
    """
    # Call the Device for the host since we are going to need device.id in order to apply the interface to it
    device = nb.dcim.devices.get(name=task.host.name)

    route = task.run(task=netmiko_send_command, command_string="route -n | grep -m 1 0.0.0.0")
    gateway = route[0].result.replace('0.0.0.0', "").strip().split(" ")[0]
    interface = route[0].result.replace('0.0.0.0', "").strip().split(" ")[-1]

    # Find IP Address and NetMask
    ip_mask_info = task.run(netmiko_send_command, command_string=f"ifconfig -a {interface} | grep inet")
    ip_addy = ip_mask_info[0].result.split()[1]
    netmask = ip_mask_info[0].result.split()[3]

    # convert dotted netmask to proper format for NetBox
    mask = IPAddress(netmask).netmask_bits()

    # format IP for NetBox
    nb_ip = str(ip_addy) + "/" + str(mask)

    try:
        if nb.ipam.ip_addresses.get(address=ip_addy) is None:
            nb.ipam.ip_addresses.create({'address': nb_ip, 'status': 'reserved'})
    except:
        print(f"Error creating {nb_ip} in NetBox")

    # Find mac address
    eth_mac_address = task.run(netmiko_send_command, command_string=f"ifconfig -a {interface} | grep ether")
    eth_mac = eth_mac_address[0].result.split()[1]

    # Find active interface speed
    eth_speed = task.run(netmiko_send_command, command_string=f"ethtool {interface} | grep Speed")
    speed = eth_speed[0].result.split(":")[-1]

    # Define the various interface types based on the speed
    if '25000' in speed:
        int_type = '25gbase-x-sfp28'

    elif '100000' in speed:
        int_type = '100gbase-x-qsfp28'

    else:
        int_type = '10gbase-x-sfpp'

    eth_mtu_setting = task.run(netmiko_send_command, command_string=f"ifconfig -a {interface} | grep mtu")
    eth_mtu = eth_mtu_setting[0].result.split()[-1]

    try:
        interface = nb.dcim.interfaces.create({'device': device.id, 'name': interface, 'type': int_type, 'mac_address': eth_mac, 'mtu': eth_mtu})
        print(f"{interface} has been created with InterfaceID:{interface.id}")
    except:
        print(f"Error creating {interface} eth interface")

    # Add IP Address to ETH interface
    interface = nb.dcim.interfaces.get(interface.id)

    ip = nb.ipam.ip_addresses.filter(ip_addy)

    for i in ip:
        try:
            i.update({'assigned_object_type': 'dcim.interface', "assigned_object_id": interface.id,
                     "assigned_object": interface.name, 'address': i.address})
        except:
            print("Error updating the eth IP Address")

        device.update({'primary_ip4': {'address': i.address}})

    # get LLDP Neighbor and port
    lldp = task.run(netmiko_send_command, command_string="sudo lldpcli show neighbors")

    lldp_mac = lldp[0].result.split("\n")[5].split()[-1].strip()
    lldp_neighbor = lldp[0].result.split("\n")[6].split(":")[-1].strip()
    lldp_port = lldp[0].result.split("\n")[12].split(": ")[-1].strip()

    # Start the process of connecting to the correct port based of LLDP
    if lldp_neighbor is None:
        pass

    if lldp_port is None:
        pass

    else:
        interfaces = nb.dcim.interfaces.all()

        for i in interfaces:
            if i.device.display == lldp_neighbor:
                if lldp_port in i.name:
                    print(f"{i.name} RouterID:{i.id} ")
                    router_int_id = i.id

        # Make the actual connection between the endpoints
        try:
            nb.dcim.cables.create(termination_a_type="dcim.interface", termination_b_type="dcim.interface",
                                  termination_a_id=interface.id, termination_b_id=router_int_id)
            print(f"{interface.id} successfully connected to {router_int_id}")
        except:
            print("Error making the network connection between endpoints")


def create_bmc_interface(task: Task) -> Result:
    """
    Send commands using netmiko to create a BMC Info.

    Create the BMC Interface and add the mac address and IP Address
    """
    device = nb.dcim.devices.get(name=task.host.name)

    bmc_ip_address = task.run(netmiko_send_command, command_string="sudo ipmitool lan print | grep 'IP Address'")
    bmc_ip = bmc_ip_address[0].result.split("\n")[1].split(":")[1]

    bmc_subnet_mask = task.run(netmiko_send_command, command_string="sudo ipmitool lan print | grep 'Subnet Mask'")
    bmc_netmask = bmc_subnet_mask[0].result.split("\n")[0].split(":")[1].strip()

    # convert dotted netmask to proper format for NetBox
    bmc_mask = IPAddress(bmc_netmask).netmask_bits()

    # format IP for NetBox
    nb_bmc_ip = str(bmc_ip) + "/" + str(bmc_mask)

    try:
        if nb.ipam.ip_addresses.get(bmc_ip) is None:
            nb.ipam.ip_addresses.create({'address': nb_bmc_ip, 'status': 'dhcp'})
    except:
        print(f"Error creating BMC {nb_bmc_ip} in NetBox")

    bmc_mac_address = task.run(netmiko_send_command, command_string="sudo ipmitool lan print | grep 'MAC Address'")
    bmc_mac = bmc_mac_address[0].result.split(" : ")[1]

    try:
        bmc_interface = nb.dcim.interfaces.create({'device': device.id, 'name': 'bmc', 'type': '1000base-t', 'mac_address': bmc_mac, 'mtu': '1500'})
        print(f"{bmc_interface} has been created with InterfaceID: {bmc_interface.id}")
    except:
        print(f"Error creating {bmc_interface} interface")

    # Add IP Address to BMC interface
    interfaces = nb.dcim.interfaces.get(bmc_interface.id)

    ip = nb.ipam.ip_addresses.filter(bmc_ip)

    for i in ip:
        try:
            i.update({'assigned_object_type': 'dcim.interface', "assigned_object_id": interfaces.id,
                     "assigned_object": interfaces.name, 'address': i.address})
        except:
            print(f"Error updating {bmc_ip} BMC IP Address")

def update_power(task: Task) -> Result:
    """
    Send commands using netmiko to create and update power info.

    Create Power Supplies on Parent device if necessary and update the max and allocated power in NetBox
    """
    device = nb.dcim.devices.get(name=task.host.name)

    result = task.run(netmiko_send_command, command_string="sudo dmidecode -t39 | grep 'Power Capacity'")
    max_power = result[0].result.split(":")[-1].strip('W').strip()

    # If child (server) has it's chassis (parent) already defined then try and add the power for it
    if device.parent_device is not None:

        # Define the power ports on the chassis if they do not already exist
        if nb.dcim.power_ports.get(device.parent_device.id) is None:
            primary_power = nb.dcim.power_ports.create({"device": device.parent_device.id, "name": "Primary Power Supply"})
            backup_power = nb.dcim.power_ports.create({"device": device.parent_device.id, "name": "Backup Power Supply"})

        # Grab the max and allocated power draws too see if they are empty
        primary = nb.dcim.power_ports.get(primary_power.id)
        backup = nb.dcim.power_ports.get(backup_power.id)

        # Only update the power on the chassis if it is not already defined
        if primary.maximum_draw is None:
            allocated_power = int(max_power) / 4
            primary.update({'maximum_draw': max_power, 'allocated_draw': allocated_power})
        if backup.maximum_draw is None:
            backup.update({'maximum_draw': max_power, 'allocated_draw': allocated_power})


if __name__ == "__main__":
    nr.run(task=update_server)
    nr.run(task=create_interface)
    nr.run(task=create_bmc_interface)
    nr.run(task=update_power)