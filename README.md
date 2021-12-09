# netbox-auto-provision-scripts  (Work in Progress)

Two scripts created to import Linux servers into NetBox. Tested on Ubuntu and CentOS. All hosts should have LLDP enabled so connections can be mapped in NetBox. 

The main provision script is intended to be run on a child device (server) that will be racked into a parent chassis. In our case since most of our servers are blade types we choose to rack 1 node systems into a parent chassis for overall consistency. This script was tested on 1 Node parent/child as well.

1) Seed NetBox with server data gathered with NorNir and Napalm via LLDP and ARP info. The minios script creates a base system in NetBox. 

You can bypass the script and just create a base system (CSV Import) in NetBox as shown below and run the main provision script on that.  

Keep in mind the main provision script still needs valid DNS working. The ARP seed script also outputs data for you to put into /etc/hosts on your provisioning server so you can SSH to the systems without creating IP and Interfaces in NetBox since the script will do that for you anyway. It's a bit of a hack I stumbled across but seems to work well until I have time to change it.

###### Provision script must have a "Base" system in place. If you used the seed script you will also have IP's you need to add to /etc/host file so no DNS is needed for SSH to work. 

<img width="1271" alt="shell-system-no-interface-ip" src="https://user-images.githubusercontent.com/50723251/145331652-3e240612-b83e-4068-99f7-a5a0fd3469bc.png">

###### This is the parent chassis that the script is going to install the child server into, it will also add power connections and info based off server
<img width="1339" alt="parent-empty-bay-no-power" src="https://user-images.githubusercontent.com/50723251/145331670-b031caf0-fd70-4ff1-9ac3-59ada6f24b3b.png">


###### The main provision script will take the shell from above and fill in many key details for you automatically.   
2) Gather all facts about a server and add them to NetBox. This includes manafucturer, product type, serial number, asset tags, ethernet interface and IP
BMC interface and IP and it will also make the interface connections in NetBox based of LLDP information it finds so that you will be able to see the active LLDP  connections in NetBox GUI. 

3) Still a work in progress as time allows but there are lots of things I'd like to fix in this script. It's a learning process and grew very organically. 

**Final State** with Device Type, Serial, Role, Rack, Status, and Custom Fields for BIOS and BMC info 
<img width="1336" alt="System-Info" src="https://user-images.githubusercontent.com/50723251/145328806-d0c91468-20e1-4900-b501-bc4a86a45577.png">

LLDP used to make the connections in netbox, ARP and IPMITOOL used to find ETH and BMC IP addresses
<img width="1318" alt="LLDP-Interface-IP" src="https://user-images.githubusercontent.com/50723251/145328824-a5bd03de-3b8e-44d9-ab92-9c26fe7de321.png">

Child Server is racked into the parent based off the chassis serial number. Set the node as a script option. Script still works if wrong node selcted, it will just leave the system unracked. Run the script again with the correct node and it will slot it correctly.  
<img width="1346" alt="Device Bay" src="https://user-images.githubusercontent.com/50723251/145328848-22ee95d7-09d0-45db-b7c8-20b6be4edde5.png">

Power connections created on the chassis and max power and allocation also set.
<img width="1350" alt="Power-Chassis" src="https://user-images.githubusercontent.com/50723251/145328858-2aca0ed7-8586-4944-8f6a-c04a384521ed.png">
