# netbox-auto-provision-scripts  (Work in Progress)

Two scripts created to import Linux servers into NetBox. Tested on Ubuntu and CentOS. All hosts should have LLDP enabled so connections can be mapped in NetBox. 

1) Seed NetBox with server data gathered with NorNir and Napalm via LLDP and ARP info. This script outputs hostame and IP address so you can paste 
this info into your /etc/hosts file so that you don't need to have valid DNS entries for the next script. 

2) Gather all facts about a server and add them to NetBox. This includes manafucturer, product type, serial number, asset tags, ethernet interface and IP
BMC interface and IP and it will also make the interface connections in NetBox based of LLDP information it finds so that you will be able to see the active LLDP  connections in NetBox GUI. 
