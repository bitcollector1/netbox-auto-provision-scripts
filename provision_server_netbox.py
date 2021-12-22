"""
Script to update a server/minios details in NetBox.

1. LLDP needs to be enabled on the host for this script to properly make the network connections.
"""
import os
import sys
import requests
import pynetbox

from netaddr import IPAddress
from nornir import InitNornir
from nornir.core.task import Task, Result
from nornir_napalm.plugins.tasks import napalm_get
from nornir_netmiko.tasks import netmiko_send_command

session = requests.Session()
session.verify = '/etc/ssl/certs'

nb = pynetbox.api("https://your.netbox.com", "012345678909876543321234345356345")
nb.http_session = session

nr = InitNornir(config_file="nornir_nb_provision.yaml")

nr.inventory.defaults.username = sys.argv[1]
nr.inventory.defaults.password = sys.argv[2]
ip_address = sys.argv[3]
hostname = sys.argv[4]
node = sys.argv[5]

# Default to Node A if choice is not made
if not node:
    node = 'NODE-A'

# Code to get an IP onto the box so we can ssh via nornir
nb_ips = nb.ipam.ip_addresses.filter(q=ip_address)

# Code returns a record set so we need to grab the IP object so we can run update on it
for i in nb_ips:
    nb_ip = i

# setup a dummy interface so nornir can ssh to the device without DNS
dummy_int = nb.dcim.interfaces.create({'device': {'name': hostname}, 'name': 'eth0', 'type': '1000base-t'})

# add IP address to system
nb_ip.update({'assigned_object_type': 'dcim.interface', "assigned_object_id": dummy_int.id, "assigned_object": dummy_int.name, 'address': nb_ip.address})

# END Tentant Name
tenant_name = 'HWE'

host = nr.inventory.hosts

# END ROLE of device
device_role_name = 'server'

# END STATUS of device
device_status = 'active'

# END Platform of device
platform_type = 'linux'


# exit if no hosts found
if len(host) < 1:
    print("No Hosts Found!")
    sys.exit(0)
else:
    print(host)

def enable_lldp(task: Task) -> Result:
  
    device = nb.dcim.devices.get(name=task.host.name)

    # Try and enable LLDP for all hosts
    lldp_enable = task.run(netmiko_send_command, command_string = "sudo systemctl --now enable lldpd")
    print(lldp_enable.result)
    
    # Configure LLDP to use ifname instead of the default --> mac address 
    lldp_ifname = task.run(netmiko_send_command, command_string = "sudo lldpcli configure lldp portidsubtype ifname") 
    
    # Intel NIC's Hijack LLDP packets so we need to find the bus used
    result = task.run(netmiko_send_command, command_string="sudo lspci | grep -i 'ethernet'")
    nics = result[0].result.split("\n")[0]
    
    controller = nics.find('controller')
    vendor = nics[controller:].split(" ")[1].lower()  # get first word after "controller:"
    print(vendor)
    
    result = task.run(netmiko_send_command, command_string="lshw -class network -businfo")
    bus_info = result[0].result

    index = bus_info.find('pci@')                 # stores the index of a substring or char
    interface = bus_info[index:].split("\n")      # returns the chars AFTER the seen char or substring
    interface.pop()                               # WARNING: output may be incomplete or inaccurate 
    
    for i in interface:
        interface_bus = (i.split()[0].replace("pci@0000:", ""))
        interface_name = (i.split()[1].replace("pci@0000:", ""))
        
        if 'intel' in vendor:
            # Stop Intel from Hijacking the LLDP Packets
            FU_INTEL = (f" echo lldp stop | sudo tee -a /sys/kernel/debug/i40e/0000:{interface_bus}/command > /dev/null")
        
            task.run(netmiko_send_command, command_string = FU_INTEL)
            print(FU_INTEL)


def create_interface(task: Task) -> Result:
    """
    Create Interface, Add IP and Connect to host interface to switch interface.

    LLDP Needs to be enabled on the switch AND the host for the connection to be made
    """
    # Call the Device for the host since we are going to need device.id in order to apply the interface to it
    device = nb.dcim.devices.get(name=task.host.name)

    route = task.run(task=netmiko_send_command, command_string="route -n | grep -m 1 0.0.0.0")
    gateway = route[0].result.replace('0.0.0.0', "").strip().split(" ")[0]
    int_name = route[0].result.replace('0.0.0.0', "").strip().split(" ")[-1]
    
    # Find IP Address and NetMask
    ip_mask_info = task.run(netmiko_send_command, command_string=f"ifconfig -a {int_name} | grep inet")
    ip_addy = ip_mask_info[0].result.split()[1]
    netmask = ip_mask_info[0].result.split()[3]

    # convert dotted netmask to proper format for NetBox
    mask = IPAddress(netmask).netmask_bits()

    # format IP for NetBox
    nb_ip = str(ip_addy) + "/" + str(mask)

    if not nb.ipam.ip_addresses.get(q=ip_addy, mask_length=mask):
        try:
            nb.ipam.ip_addresses.create({'address': nb_ip, 'status': 'reserved'})
            print(f"ETH Address {nb_ip} added to NetBox")
        except:
            print(f"Error creating ETH address {nb_ip} in NetBox")
    else:
        print(f"ETH address: {nb_ip} already exists in NetBox")

    # Find mac address
    eth_mac_address = task.run(netmiko_send_command, command_string=f"ifconfig -a {int_name} | grep ether")
    eth_mac = eth_mac_address[0].result.split()[1]

    # Find active interface speed
    eth_speed = task.run(netmiko_send_command, command_string=f"ethtool {int_name} | grep Speed")
    speed = eth_speed[0].result.split(":")[-1]

    # Define the various interface types based on the speed
    if '25000' in speed:
        int_type = '25gbase-x-sfp28'

    elif '100000' in speed:
        int_type = '100gbase-x-qsfp28'

    else:
        int_type = '10gbase-x-sfpp'

    eth_mtu_setting = task.run(netmiko_send_command, command_string=f"ifconfig -a {int_name} | grep mtu")
    eth_mtu = eth_mtu_setting[0].result.split()[-1]

    interface = nb.dcim.interfaces.get(device=device.name, name=int_name)

    if interface is None:
        try:
            interface = nb.dcim.interfaces.create({'device': device.id, 'name': int_name, 'type': int_type, 'mac_address': eth_mac, 'mtu': eth_mtu})
            print(f"{interface} has been created with InterfaceID:{interface.id}")
        except:
            print(f"Error creating {int_name} eth interface")

    # Add IP Address to ETH interface
    ip = nb.ipam.ip_addresses.filter(address=ip_addy)

    for i in ip:
        try:
            i.update({'assigned_object_type': 'dcim.interface', "assigned_object_id": interface.id,
                     "assigned_object": interface.name, 'address': i.address})

            print(f"Successfully added {i.address} to interface {interface.name}")
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
        print("NO LLDP NEIGHBOR FOUND")
        pass

    else:
        interfaces = nb.dcim.interfaces.all()

        for i in interfaces:
            if i.device.name == lldp_neighbor:
                if lldp_port in i.name:
                    print(f"{i.name} RouterID:{i.id} ")
                    router_int_id = i.id

        if not nb.dcim.cables.get(termination_a_type="dcim.interface", termination_b_type="dcim.interface", termination_a_id=interface.id, termination_b_id=router_int_id):
            # Make the actual connection between the endpoints
            try:
                nb.dcim.cables.create(termination_a_type="dcim.interface", termination_b_type="dcim.interface",
                                      termination_a_id=interface.id, termination_b_id=router_int_id)
                print(f"{interface.id} successfully connected to {router_int_id}")
            except:
                print(f"Error making the network connection between endpoints {interface.id} {router_int_id} ")
        else:
            print(f"Connections already found between {interface.id} and {router_int_id} ")

    # remove dummy interface when no longer needed
    dummy_int.delete()

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

    if not nb.ipam.ip_addresses.get(q=bmc_ip, mask_length=bmc_mask):
        try:
            nb.ipam.ip_addresses.create({'address': nb_bmc_ip, 'status': 'dhcp'})
            print(f"BMC IP Address {nb_bmc_ip} added to NetBox")
        except:
            print(f"Error creating BMC {nb_bmc_ip} in NetBox")
    else:
        print(f"BMC address: {nb_bmc_ip} already exists in NetBox")

    bmc_mac_address = task.run(netmiko_send_command, command_string="sudo ipmitool lan print | grep 'MAC Address'")
    bmc_mac = bmc_mac_address[0].result.split(" : ")[1]

    bmc_interface = nb.dcim.interfaces.get(device=device.name, name='bmc')

    if bmc_interface is None:
        try:
            bmc_interface = nb.dcim.interfaces.create({'device': device.id, 'name': 'bmc', 'type': '1000base-t', 'mac_address': bmc_mac, 'mtu': '1500'})
            print(f"{bmc_interface} has been created with InterfaceID: {bmc_interface.id}")
        except:
            print(f"Error creating {bmc_interface} interface")

    ip = nb.ipam.ip_addresses.get(q=bmc_ip, mask_length=24)
 
    try:
        ip.update({'assigned_object_type': 'dcim.interface', "assigned_object_id": bmc_interface.id,
                  "assigned_object": bmc_interface.name, 'address': ip.address})

        print(f"Successfully added {ip.address} to interface {bmc_interface.name}")
    except:
        print(f"Error updating BMC {bmc_ip} on interface {bmc_interface.name}")


def custom_fields(task: Task) -> Result:
    """
    Send commands using netmiko to update all of the custom fields.

    Some of this current info will be going into device inventory and may be removed from here to avoid data duplication
    """
    device = nb.dcim.devices.get(name=task.host.name)
    # get SKU
    result = task.run(netmiko_send_command, command_string="sudo dmidecode -t1 | grep SKU")
    sku = result[0].result.split(":")[-1]

    # get_bmc_version
    result = task.run(netmiko_send_command, command_string="sudo ipmitool mc info | grep Version")
    bmc_ver = result[0].result.split(":")[-1]

    # get_bmc_Firmware
    result = task.run(netmiko_send_command, command_string="sudo ipmitool mc info | grep 'Firmware Revision'")
    bmc_firm = result[0].result.split(":")[-1]

    # get_bios_version
    result = task.run(netmiko_send_command, command_string="sudo dmidecode -t0 | grep Version")
    bios_ver = result[0].result.split(":")[-1]

    # get bios_rev
    result = task.run(netmiko_send_command, command_string="sudo dmidecode -t 0")
    bios_rev = result[0].result.split("\n")[-2].split(":")[-1]

    try:
        # Update all of the custom fields that were gathered above
        custom_fields = device.update({"custom_fields": {'ebay_sku': sku, 'bios_revision': bios_rev, 'bios_version':
                                                         bios_ver, 'bmc_firmware': bmc_firm, 'bmc_version': bmc_ver}})

        print(f"Successfully updated custom_fields for {device.name}")
    except:
        print(f"Not able to update custom_fields for {device.name}")


def update_server(task: Task) -> Result:
    """
    Send commands using netmiko to update the server info .

    Create Manufacturer and Product if it does not already exist
    Update Manufacturer, Product, Serial, Asset_Tag, OS_Version
    """
    if not nb.dcim.device_roles.get(name=device_role_name):
        print(f"Device Role: {device_role_name} is not valid, exiting!")
        sys.exit()

    if not nb.dcim.devices.filter(value=device_status):
        print(f"Device Status: {device_status} is not valid, exiting!")
        sys.exit()

    if not nb.dcim.platforms.get(name=platform_type):
        print(f"Platform Type: {platform_type} is not valid, exiting!")
        sys.exit()

    if not nb.tenancy.tenants.get(name=tenant_name):
        print(f"Tenant Name: {tenant_name} is not valid, exiting!")
        sys.exit()

    # call a device object and then use that object to update a device
    device = nb.dcim.devices.get(name=task.host.name)

    system_manufacturer = task.run(netmiko_send_command, command_string="sudo dmidecode -s system-manufacturer")
    manufacturer = system_manufacturer[0].result

    if 'Dell' in manufacturer:
        manufacturer = 'Dell'

    if 'Quanta' in manufacturer:
        manufacturer = 'QCT'

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

    chassis_serial_number = task.run(netmiko_send_command, command_string="sudo dmidecode -s chassis-serial-number")
    chassis_serial = chassis_serial_number[0].result

    # This should always be a child
    baseboard_asset_tag = task.run(netmiko_send_command, command_string="sudo dmidecode -s baseboard-asset-tag")
    baseboard_asset = baseboard_asset_tag[0].result

    # This should alyways be a parent --> 1RU systems do not have a parent
    chassis_asset_tag = task.run(netmiko_send_command, command_string="sudo dmidecode -s  chassis-asset-tag")
    chassis_asset = chassis_asset_tag[0].result

    if baseboard_asset.isdigit():
        asset = baseboard_asset

    elif chassis_asset.isdigit():
        asset = chassis_asset

    else:
        asset = None
        print(f" Asset Tags are invalid, setting to None --> Baseboard:{baseboard_asset}  Chassis:{chassis_asset} ")

    child = nb.dcim.devices.get(name=device.name)

    # There is no child.parent_device at this point, we still have to set it
    parent = nb.dcim.devices.get(serial=chassis_serial)
    
    if parent:
        if node is not None:
            bay = nb.dcim.device_bays.get(device_id=parent.id, name=node)

            if bay.installed_device is not None:
                print(f"Error installing {child} into {parent}, Found existing device: {bay.installed_device}")

            if bay.installed_device is None:
                bay.installed_device = child
                if bay.save():
                    print(f"successfully installed: {child} into: {parent} Slot: {node}")
    else: 
        print ("No Parent Found to slot Node into, you will have to do this manually!")
    
    release = task.run(netmiko_send_command, command_string="cat /etc/*release* | grep PRETTY_NAME")
    os_ver = release[0].result.split("=")[-1].replace("(Core)", "").strip('"').strip()

    slug_os_name = os_ver.lower().replace(".", "-").replace(" ", "-")

    try:
        if not nb.extras.tags.get(name=os_ver):
            nb.extras.tags.create({'name': os_ver, 'slug': slug_os_name, 'color': '808080'})
    except:
        print(f" Could not create the tag for{os_ver} {slug_os_name}")

    try:
        if parent:
            device.update({'name': device.name, 'device_role': {'name': device_role_name}, 'device_type': {'model': device_type},
                           'status': device_status, 'site': {'name': parent.site.name}, 'rack_name': parent.rack,
                           'serial': serial, 'asset_tag': asset, 'platform': {'name': platform_type},
                           'tenant': {'name': tenant_name}, 'tags': [{'name': os_ver}]})
        else: 
            device.update({'name': device.name, 'device_role': {'name': device_role_name}, 'device_type': {'model': device_type},
                           'status': device_status, 'site': {'name': "1103 Platform Engineering Lab"},
                           'serial': serial, 'asset_tag': asset, 'platform': {'name': platform_type},
                           'tenant': {'name': tenant_name}, 'tags': [{'name': os_ver}]})
            
        print(f"Successfully updated Server Info for: {device.name}")

    except:
        print(f"Error updating the device info {device.name} {device_type} {asset} {parent.rack}")
        
    if not parent:
        print("No parent defined, so no power can be added, Exiting!")
        sys.exit(0)
        
    result = task.run(netmiko_send_command, command_string="sudo dmidecode -t39 | grep 'Power Capacity'")
    max_power = result[0].result.split(":")[-1].strip('W').strip()
    
    if not max_power.isdigit():
        print("No Power found")
        sys.exit(0)
    
    if not nb.dcim.power_ports.filter(device=parent.name):
        try: 
            primary_power = nb.dcim.power_ports.create({"device": parent.id, "name": "Primary Power Supply"})
            backup_power = nb.dcim.power_ports.create({"device": parent.id, "name": "Backup Power Supply"})
        except: 
            print(f"failed to create the power ports on {parent.name}")
    
    primary_power = nb.dcim.power_ports.get(q='Primary Power Supply', device=parent.name)
    
    if primary_power:
        primary = nb.dcim.power_ports.get(id=primary_power.id)
         
        if primary.maximum_draw is None:
            allocated_power = int(max_power) / 4
            primary.update({'maximum_draw': max_power, 'allocated_draw': allocated_power})
            print(f"Primary power supply updated with max power: {max_power}  allocated power: {allocated_power}") 
        else:
            print(f"Primary Power already defined Max:{primary.maximum_draw} Allocated: {primary.allocated_draw}")
    
    backup_power = nb.dcim.power_ports.get(q='Backup Power Supply', device= parent.name)
    
    if backup_power:     
        backup = nb.dcim.power_ports.get(id=backup_power.id)
            
        if backup.maximum_draw is None:
            backup.update({'maximum_draw': max_power, 'allocated_draw': allocated_power})
            print(f"Backup power supply updated with max power: {max_power} allocated power: {allocated_power}")
        else:
            print(f"Backup Power already defined Max:{backup.maximum_draw} Allocated: {backup.allocated_draw}")


if __name__ == "__main__":
    nr.run(task=enable_lldp)
    nr.run(task=create_interface)
    nr.run(task=create_bmc_interface)
    nr.run(task=custom_fields)
    nr.run(task=update_server)
