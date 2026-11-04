#!/usr/bin/env python3
"""
Interactive Network Automation Script
Handles IP configuration, routing, VLANs, SNMPv2c, and NTP using netmiko and pysnmp
Modified for FastAPI integration with additional methods
"""

import os
import sys
import shutil
import re
import time
import logging
import asyncio
import subprocess
import socket
import json
import platform
from datetime import datetime
import difflib
import schedule
from fastapi import WebSocket
from typing import Dict, Any, Optional, List
from pysnmp.entity.rfc3413 import ntfrcv
from pysnmp.entity import engine, config
from pysnmp.carrier.asyncore.dgram import udp
import threading


try:
    from netmiko import ConnectHandler
    from netmiko.exceptions import NetmikoTimeoutException, NetmikoAuthenticationException
    NETMIKO_AVAILABLE = True
except ImportError:
    NETMIKO_AVAILABLE = False
    print("Warning: Netmiko not available. SSH functionality will be limited.")

try:
    from pysnmp.hlapi import (
        getCmd, SnmpEngine, CommunityData, UdpTransportTarget,
        ContextData, ObjectType, ObjectIdentity
    )
    PYSNMP_AVAILABLE = True
except ImportError:
    PYSNMP_AVAILABLE = False
    print("Warning: PySNMP not available. SNMPv2c functionality will be limited.")

logger = logging.getLogger(__name__)

class InteractiveNetworkAutomation:
    def __init__(self, config_file: str = "network_config.json"):
        self.logger = logging.getLogger(__name__)
        self.device_credentials: Dict[str, Dict[str, str]] = {}
        self.current_device_ip: Optional[str] = None
        self.current_device: Optional[str] = None
        self.session_history: List[Dict[str, str]] = []
        self.config_file = config_file
        
        self.trap_clients = []
        self.loop = None
        self.default_snmp_community = "public"
        self.loop: asyncio.AbstractEventLoop = None
        self.load_config()

    def load_config(self):
        try:
            config_path = os.path.abspath(self.config_file)
            self.logger.info(f"Attempting to load config from: {config_path}")
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.device_credentials = config.get('devices', {})
                    self.default_snmp_community = config.get('default_snmp_community', 'public')
                    self.logger.info(f"Loaded config: {self.device_credentials}")
            else:
                self.logger.error(f"Config file not found at: {config_path}")
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse config file {self.config_file}: {str(e)}")
        except Exception as e:
            self.logger.error(f"Failed to load config file {self.config_file}: {type(e).__name__}: {str(e)}")

    def save_config(self):
        config = {
            "default_snmp_community": self.default_snmp_community,
            "devices": self.device_credentials
        }
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4)
            self.logger.info(f"Saved config to: {self.config_file}")
        except Exception as e:
            self.logger.error(f"Failed to save config: {type(e).__name__}: {str(e)}")

    def log_action(self, action: str, device: str = None, result: str = "Success"):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        device = device or self.current_device or "N/A"
        self.session_history.append({
            'timestamp': timestamp,
            'device': device,
            'action': action,
            'result': result
        })
        return f"[{timestamp}] {device} - {action} - {result}"

    def show_session_history(self):
        output = ["Session History:"]
        for entry in self.session_history:
            output.append(f"{entry['timestamp']} - {entry['device']} - {entry['action']} - {entry['result']}")
        return '\n'.join(output) if self.session_history else "No session history available"

    async def ping_device(self, ip_address: str) -> bool:
        try:
            if platform.system().lower() == "windows":
                ping_cmd = ["ping", "-n", "1", "-w", "3000", ip_address]
            else:
                ping_cmd = ["ping", "-c", "1", "-W", "3", ip_address]
            self.logger.info(f"Executing ping command: {' '.join(ping_cmd)}")
            ping_path = shutil.which("ping") or "ping"
            ping_cmd[0] = ping_path
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, lambda: subprocess.run(
                ping_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=0x08000000 if platform.system().lower() == "windows" else 0
            ))
            stdout_decoded = result.stdout
            stderr_decoded = result.stderr
            returncode = result.returncode
            if returncode != 0:
                self.logger.error(f"Ping failed for {ip_address}: returncode={returncode}, stdout={stdout_decoded}, stderr={stderr_decoded}")
            else:
                self.logger.info(f"Ping succeeded for {ip_address}: stdout={stdout_decoded}")
            return returncode == 0
        except FileNotFoundError as e:
            self.logger.error(f"Ping error for {ip_address}: ping command not found - {str(e)}")
            return False
        except PermissionError as e:
            self.logger.error(f"Ping error for {ip_address}: permission denied - {str(e)}")
            return False
        except Exception as e:
            self.logger.error(f"Ping error for {ip_address}: unexpected error - {type(e).__name__}: {str(e)}")
            return False

    def get_device_connection(self, ip_address: str, device_type: str = None) -> Optional[ConnectHandler]:
        self.logger.info(f"Available credentials: {self.device_credentials}")
        if not NETMIKO_AVAILABLE:
            self.logger.error(f"Failed to connect to {ip_address}: Netmiko not available")
            return None
        if ip_address not in self.device_credentials:
            self.logger.error(f"Failed to connect to {ip_address}: No credentials found in config")
            return None
        creds = self.device_credentials[ip_address]
        device_types = device_type if device_type else [creds.get('device_type', 'cisco_ios')]
        if isinstance(device_types, str):
            device_types = [device_types]
        for dtype in device_types:
            try:
                device = {
                    'device_type': dtype,
                    'host': ip_address,
                    'username': creds['username'],
                    'password': creds['password'],
                    'secret': creds.get('secret', ''),
                    'timeout': 90,
                    'session_timeout': 120,
                    'global_delay_factor': 2.0,
                    'session_log': 'netmiko_session.log',
                    "banner_timeout": 10,
                    'disabled_algorithms': {
                        'pubkeys': ['rsa-sha2-256', 'rsa-sha2-512'],
                        'kex': ['diffie-hellman-group-exchange-sha256'],
                        'macs': ['hmac-sha2-256', 'hmac-sha2-512']
                    }
                }
                connection = ConnectHandler(**device)
                if device['secret']:
                    connection.enable()
                self.logger.info(f"Connected to {ip_address} using {dtype}")
                return connection
            except (NetmikoTimeoutException, NetmikoAuthenticationException) as e:
                self.logger.error(f"Failed to connect to {ip_address} with {dtype}: {str(e)}")
                continue
            except Exception as e:
                self.logger.error(f"Unexpected error connecting to {ip_address} with {dtype}: {type(e).__name__}: {str(e)}")
                continue
        self.logger.error(f"Could not connect to {ip_address} with any device type")
        return None

    def set_current_device(self, ip_address: str) -> str:
        if ip_address not in self.device_credentials:
            self.logger.error(f"Device {ip_address} not found in credentials")
            return f"Error: Device {ip_address} not found in credentials"
        self.current_device_ip = ip_address
        self.current_device = ip_address
        result = self.log_action(f"Set current device to {ip_address}")
        return result

    async def test_connectivity(self, ip_address: str) -> str:
        if await self.ping_device(self.current_device_ip):
            result = self.log_action(f"Ping test to {ip_address}", ip_address)
            return f"Ping successful to {ip_address}"
        else:
            result = self.log_action(f"Ping test to {ip_address}", ip_address, "Failed")
            return f"Ping failed to {ip_address}"

    def show_device_info(self, ip_address: str) -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            
            result = self.log_action(f"Show device info for {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            output = connection.send_command("show version",read_timeout=120)
            result = self.log_action(f"Show device info for {ip_address}", ip_address)
            
            return output
        except Exception as e:
            result = self.log_action(f"Show device info for {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    def execute_custom_command(self, ip_address: str, command: str) -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            result = self.log_action(f"Execute command '{command}' on {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            output = connection.send_command(command,read_timeout=120)
            result = self.log_action(f"Execute command '{command}' on {ip_address}", ip_address)
            return output
        except Exception as e:
            result = self.log_action(f"Execute command '{command}' on {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    def show_interface_status(self, ip_address: str) -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            result = self.log_action(f"Show interface status for {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            output = connection.send_command("show ip interface brief",read_timeout=120)
            result = self.log_action(f"Show interface status for {ip_address}", ip_address)
            return output
        except Exception as e:
            result = self.log_action(f"Show interface status for {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    def configure_interface_ip(self, ip_address: str, interface: str, ip_addr: str, subnet_mask: str) -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            result = self.log_action(f"Configure interface {interface} IP on {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            commands = [
                f"interface {interface}",
                f"ip address {ip_addr} {subnet_mask}",
                "no shutdown"
            ]
            output = connection.send_config_set(commands, exit_config_mode=False, read_timeout=120, delay_factor=2)
            connection.send_command("write memory", expect_string=r"#", read_timeout=90)
            result = self.log_action(f"Configure interface {interface} IP on {ip_address}", ip_address)
            return output
        except Exception as e:
            result = self.log_action(f"Configure interface {interface} IP on {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    def show_ip_configuration(self, ip_address: str) -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            result = self.log_action(f"Show IP configuration for {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            output = connection.send_command("show running-config | include ip address", expect_string=r"#", read_timeout=90)
            result = self.log_action(f"Show IP configuration for {ip_address}", ip_address)
            return output
        except Exception as e:
            result = self.log_action(f"Show IP configuration for {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    def configure_loopback(self, ip_address: str, loopback_num: int, loopback_ip: str, subnet_mask: str) -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            result = self.log_action(f"Configure loopback {loopback_num} on {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            commands = [
                f"interface loopback {loopback_num}",
                f"ip address {loopback_ip} {subnet_mask}",
                "no shutdown"
            ]
            output = connection.send_config_set(commands)
            connection.send_command("write memory")
            result = self.log_action(f"Configure loopback {loopback_num} on {ip_address}", ip_address)
            return output
        except Exception as e:
            result = self.log_action(f"Configure loopback {loopback_num} on {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    def configure_dhcp_pool(self, ip_address: str, pool_name: str, network: str, subnet_mask: str, default_router: str, dns_server: str) -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            result = self.log_action(f"Configure DHCP pool on {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            commands = [
                f"ip dhcp pool {pool_name}",
                f"network {network} {subnet_mask}",
                f"default-router {default_router}",
                f"dns-server {dns_server}" if dns_server else ""
            ]
            output = connection.send_config_set(commands)
            connection.send_command("write memory")
            result = self.log_action(f"Configure DHCP pool on {ip_address}", ip_address)
            return output
        except Exception as e:
            result = self.log_action(f"Configure DHCP pool on {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    def toggle_interface(self, ip_address: str, interface: str, action: str) -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            result = self.log_action(f"Toggle interface {interface} on {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            commands = [
                f"interface {interface}",
                "shutdown" if action.lower() == "disable" else "no shutdown"
            ]
            output = connection.send_config_set(commands)
            connection.send_command("write memory")
            result = self.log_action(f"Toggle interface {interface} on {ip_address} to {action}", ip_address)
            return output
        except Exception as e:
            result = self.log_action(f"Toggle interface {interface} on {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    def configure_static_route(self, ip_address: str, dest_network: str, subnet_mask: str, next_hop: str, admin_distance: str) -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            result = self.log_action(f"Configure static route on {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            cmd = f"ip route {dest_network} {subnet_mask} {next_hop}"
            if admin_distance:
                cmd += f" {admin_distance}"
            output = connection.send_config_set(cmd)
            connection.send_command("write memory")
            result = self.log_action(f"Configure static route on {ip_address}", ip_address)
            return output
            
        except Exception as e:
            result = self.log_action(f"Configure static route on {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    def show_routing_table(self, ip_address: str) -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            result = self.log_action(f"Show routing table for {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            output = connection.send_command("show ip route")
            result = self.log_action(f"Show routing table for {ip_address}", ip_address)
            return output
        except Exception as e:
            result = self.log_action(f"Show routing table for {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    def configure_ospf(self, ip_address: str, process_id: int, router_id: str, network: str, wildcard: str, area: int) -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            result = self.log_action(f"Configure OSPF on {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            commands = [
                f"router ospf {process_id}",
                f"router-id {router_id}",
                f"network {network} {wildcard} area {area}"
            ]
            output = connection.send_config_set(commands)
            connection.send_command("write memory")
            result = self.log_action(f"Configure OSPF on {ip_address}", ip_address)
            return output
        except Exception as e:
            result = self.log_action(f"Configure OSPF on {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    def configure_eigrp(self, ip_address: str, as_number: int, network: str, wildcard: str) -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            result = self.log_action(f"Configure EIGRP on {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            commands = [
                f"router eigrp {as_number}",
                f"network {network} {wildcard}"
            ]
            output = connection.send_config_set(commands)
            connection.send_command("write memory")
            result = self.log_action(f"Configure EIGRP on {ip_address}", ip_address)
            return output
        except Exception as e:
            result = self.log_action(f"Configure EIGRP on {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    def configure_bgp(self, ip_address: str, as_number: int, router_id: str, neighbor_ip: str, neighbor_as: int) -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            result = self.log_action(f"Configure BGP on {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            commands = [
                f"router bgp {as_number}",
                f"bgp router-id {router_id}",
                f"neighbor {neighbor_ip} remote-as {neighbor_as}"
            ]
            output = connection.send_config_set(commands)
            connection.send_command("write memory")
            result = self.log_action(f"Configure BGP on {ip_address}", ip_address)
            return output
        except Exception as e:
            result = self.log_action(f"Configure BGP on {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    def show_routing_protocols(self, ip_address: str) -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            result = self.log_action(f"Show routing protocols for {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            output = connection.send_command("show ip protocols")
            result = self.log_action(f"Show routing protocols for {ip_address}", ip_address)
            return output
        except Exception as e:
            result = self.log_action(f"Show routing protocols for {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    def create_vlan(self, ip_address: str, vlan_id: int, vlan_name: str) -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            result = self.log_action(f"Create VLAN {vlan_id} on {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            base_prompt = connection.find_prompt()
            escaped_prompt = re.escape(base_prompt)
            commands = [
                f"vlan {vlan_id}",
                f"name {vlan_name}"
            ]
            output = connection.send_config_set(commands, exit_config_mode=False, read_timeout=90, delay_factor=2)
            connection.send_command("write memory", expect_string=r"#", read_timeout=30)
            result = self.log_action(f"Create VLAN {vlan_id} on {ip_address}", ip_address)
            return output
        except Exception as e:
            result = self.log_action(f"Create VLAN {vlan_id} on {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    def show_vlan_info(self, ip_address: str) -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            result = self.log_action(f"Show VLAN info for {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            output = connection.send_command("show vlan brief")
            result = self.log_action(f"Show VLAN info for {ip_address}", ip_address)
            return output
        except Exception as e:
            result = self.log_action(f"Show VLAN info for {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    def assign_port_to_vlan(self, ip_address: str, interface: str, vlan_id: int) -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            result = self.log_action(f"Assign port {interface} to VLAN {vlan_id} on {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            commands = [
                f"interface {interface}",
                "switchport mode access",
                f"switchport access vlan {vlan_id}",
                "no shutdown"
            ]
            output = connection.send_config_set(commands)
            connection.send_command("write memory")
            result = self.log_action(f"Assign port {interface} to VLAN {vlan_id} on {ip_address}", ip_address)
            return output
        except Exception as e:
            result = self.log_action(f"Assign port {interface} to VLAN {vlan_id} on {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    def configure_trunk_port(self, ip_address: str, interface: str, allowed_vlans: str) -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            result = self.log_action(f"Configure trunk port {interface} on {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            commands = [
                f"interface {interface}",
                "switchport mode trunk",
                f"switchport trunk allowed vlan {allowed_vlans}",
                "no shutdown"
            ]
            output = connection.send_config_set(commands)
            connection.send_command("write memory")
            result = self.log_action(f"Configure trunk port {interface} on {ip_address}", ip_address)
            return output
        except Exception as e:
            result = self.log_action(f"Configure trunk port {interface} on {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    def delete_vlan(self, ip_address: str, vlan_id: int) -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            result = self.log_action(f"Delete VLAN {vlan_id} on {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            commands = [
                f"no vlan {vlan_id}"
            ]
            output = connection.send_config_set(commands)
            connection.send_command("write memory")
            result = self.log_action(f"Delete VLAN {vlan_id} on {ip_address}", ip_address)
            return output
        except Exception as e:
            result = self.log_action(f"Delete VLAN {vlan_id} on {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    def show_vlan_database(self, ip_address: str) -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            result = self.log_action(f"Show VLAN database for {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            output = connection.send_command("show vlan-switch")
            result = self.log_action(f"Show VLAN database for {ip_address}", ip_address)
            return output
        except Exception as e:
            result = self.log_action(f"Show VLAN database for {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    async def ping_sweep(self, network: str, start_ip: int, end_ip: int) -> str:
        active_hosts = []
        tasks = []
        for i in range(start_ip, end_ip + 1):
            ip = f"{network}.{i}"
            tasks.append(self.ping_device(ip))
        results = await asyncio.gather(*tasks)
        for i, success in enumerate(results):
            if success:
                active_hosts.append(f"{network}.{start_ip + i}")
        result = self.log_action(f"Ping sweep on {network}.{start_ip}-{end_ip}")
        return f"Active hosts: {', '.join(active_hosts)}" if active_hosts else "No active hosts found"

    async def port_scan(self, ip_address: str, ports: str) -> str:
        port_list = [int(p.strip()) for p in ports.split(",") if p.strip()]
        open_ports = []
        for port in port_list:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex((ip_address, port))
                if result == 0:
                    open_ports.append(str(port))
                sock.close()
            except Exception:
                pass
        result = self.log_action(f"Port scan on {ip_address}")
        return f"Open ports: {', '.join(open_ports)}" if open_ports else "No open ports found"

    async def snmp_discovery(self, ip_address: str, community: Optional[str] = None) -> str:
        if not PYSNMP_AVAILABLE:
            result = self.log_action(f"SNMP discovery on {ip_address}", ip_address, "Failed: PySNMP not available")
            return "Error: PySNMP not available"
        creds = self.device_credentials.get(ip_address, {})
        community = community or creds.get('snmp_community', self.default_snmp_community)
        try:
            iterator = getCmd(
                SnmpEngine(),
                CommunityData(community, mpModel=1),
                UdpTransportTarget((ip_address,161)),
                ContextData(),
                ObjectType(ObjectIdentity('SNMPv2-MIB', 'sysDescr', 0))
            )
            error_indication, error_status, error_index, var_binds = next(iterator)
            if error_indication:
                result = self.log_action(f"SNMP discovery on {ip_address}", ip_address, f"Failed: {error_indication}")
                return f"Error: {error_indication}"
            elif error_status:
                result = self.log_action(f"SNMP discovery on {ip_address}", ip_address, f"Failed: {error_status}")
                return f"Error: {error_status}"
            else:
                output = str(var_binds[0][1])
                result = self.log_action(f"SNMP discovery on {ip_address}", ip_address)
                return output
        except Exception as e:
            result = self.log_action(f"SNMP discovery on {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"

    def show_neighbors(self, ip_address: str) -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            result = self.log_action(f"Show neighbors for {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            output = connection.send_command("show cdp neighbors")
            result = self.log_action(f"Show neighbors for {ip_address}", ip_address)
            return output
        except Exception as e:
            result = self.log_action(f"Show neighbors for {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    def discover_topology(self, seed_ip: str) -> str:
        connection = self.get_device_connection(seed_ip)
        if not connection:
            result = self.log_action(f"Discover topology from {seed_ip}", seed_ip, "Failed")
            return f"Error: Unable to connect to {seed_ip}"
        try:
            output = connection.send_command("show cdp neighbors detail",read_timeout=60)
            result = self.log_action(f"Discover topology from {seed_ip}", seed_ip)
            return output or "No topology information available"
        except Exception as e:
            result = self.log_action(f"Discover topology from {seed_ip}", seed_ip, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    def system_resources(self, ip_address: str) -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            result = self.log_action(f"Show system resources for {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            connection.send_command("terminal length 0")
            output = connection.send_command("show processes cpu | include CPU")
            output += "\n" + connection.send_command("show memory statistics")
            result = self.log_action(f"Show system resources for {ip_address}", ip_address)
            return output
        except Exception as e:
            result = self.log_action(f"Show system resources for {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    def multi_device_command(self, devices: str, command: str) -> str:
        device_list = [ip.strip() for ip in devices.split(",") if ip.strip()]
        results = []
        for ip in device_list:
            connection = self.get_device_connection(ip)
            if not connection:
                results.append(f"{ip}: Error - Unable to connect")
                self.log_action(f"Multi-device command '{command}' on {ip}", ip, "Failed")
                continue
            try:
                output = connection.send_command(command)
                results.append(f"{ip}:\n{output}")
                self.log_action(f"Multi-device command '{command}' on {ip}", ip)
            except Exception as e:
                results.append(f"{ip}: Error - {str(e)}")
                self.log_action(f"Multi-device command '{command}' on {ip}", ip, f"Failed: {str(e)}")
            finally:
                connection.disconnect()
        return "\n\n".join(results) if results else "No devices processed"

    def bulk_configuration(self, devices: str, commands: str) -> str:
        device_list = [ip.strip() for ip in devices.split(",") if ip.strip()]
        command_list = [cmd.strip() for cmd in commands.splitlines() if cmd.strip()]
        results = []
        for ip in device_list:
            connection = self.get_device_connection(ip)
            if not connection:
                results.append(f"{ip}: Error - Unable to connect")
                self.log_action(f"Bulk configuration on {ip}", ip, "Failed")
                continue
            try:
                output = connection.send_config_set(command_list,read_timeout=60)
                connection.send_command("write memory",read_timeout=60)
                results.append(f"{ip}:\n{output}")
                self.log_action(f"Bulk configuration on {ip}", ip)
            except Exception as e:
                results.append(f"{ip}: Error - {str(e)}")
                self.log_action(f"Bulk configuration on {ip}", ip, f"Failed: {str(e)}")
            finally:
                connection.disconnect()
        return "\n\n".join(results) if results else "No devices processed"

    def network_wide_vlan(self, switches: str, vlan_id: int, vlan_name: str) -> str:
        switch_list = [ip.strip() for ip in switches.split(",") if ip.strip()]
        results = []
        for ip in switch_list:
            connection = self.get_device_connection(ip)
            if not connection:
                results.append(f"{ip}: Error - Unable to connect")
                self.log_action(f"Network-wide VLAN {vlan_id} on {ip}", ip, "Failed")
                continue
            try:
                commands = [
                    f"vlan {vlan_id}",
                    f"name {vlan_name}"
                ]
                output = connection.send_config_set(commands)
                connection.send_command("write memory")
                results.append(f"{ip}:\n{output}")
                self.log_action(f"Network-wide VLAN {vlan_id} on {ip}", ip)
            except Exception as e:
                results.append(f"{ip}: Error - {str(e)}")
                self.log_action(f"Network-wide VLAN {vlan_id} on {ip}", ip, f"Failed: {str(e)}")
            finally:
                connection.disconnect()
        return "\n\n".join(results) if results else "No switches processed"

    def mass_interface_config(self, ip_address: str, interfaces: str, template: str, vlan_id: Optional[int] = None, allowed_vlans: Optional[str] = None, ip_addr: Optional[str] = None, subnet_mask: Optional[str] = None, commands: Optional[str] = None) -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            result = self.log_action(f"Mass interface config on {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            interface_list = [intf.strip() for intf in interfaces.split(",") if intf.strip()]
            config_commands = []
            for interface in interface_list:
                config_commands.append(f"interface {interface}")
                if template.lower() == "access" and vlan_id:
                    config_commands.extend([
                        "switchport mode access",
                        f"switchport access vlan {vlan_id}",
                        "no shutdown"
                    ])
                elif template.lower() == "trunk" and allowed_vlans:
                    config_commands.extend([
                        "switchport mode trunk",
                        f"switchport trunk allowed vlan {allowed_vlans}",
                        "no shutdown"
                    ])
                elif template.lower() == "routed" and ip_addr and subnet_mask:
                    config_commands.extend([
                        "no switchport",
                        f"ip address {ip_addr} {subnet_mask}",
                        "no shutdown"
                    ])
                if commands:
                    config_commands.extend([cmd.strip() for cmd in commands.splitlines() if cmd.strip()])
            output = connection.send_config_set(config_commands)
            connection.send_command("write memory")
            result = self.log_action(f"Mass interface config on {ip_address}", ip_address)
            return output
        except Exception as e:
            result = self.log_action(f"Mass interface config on {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    def backup_configuration(self, ip_address: str) -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            result = self.log_action(f"Backup configuration for {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            output = connection.send_command("show running-config")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"config_{ip_address}_{timestamp}.txt"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(output)
            result = self.log_action(f"Backup configuration for {ip_address} to {filename}", ip_address)
            return f"Configuration backed up to {filename}"
        except Exception as e:
            result = self.log_action(f"Backup configuration for {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    def restore_configuration(self, ip_address: str, config_file: str) -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            result = self.log_action(f"Restore configuration for {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            if not os.path.exists(config_file):
                result = self.log_action(f"Restore configuration for {ip_address}", ip_address, "Failed: Config file not found")
                return f"Error: Config file {config_file} not found"
            with open(config_file, 'r', encoding='utf-8') as f:
                config_lines = [line.strip() for line in f.readlines() if line.strip()]
            output = connection.send_config_set(config_lines)
            connection.send_command("write memory")
            result = self.log_action(f"Restore configuration for {ip_address} from {config_file}", ip_address)
            return output
        except Exception as e:
            result = self.log_action(f"Restore configuration for {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    def compare_configurations(self, file1: str, file2: str) -> str:
        try:
            if not (os.path.exists(file1) and os.path.exists(file2)):
                result = self.log_action(f"Compare configurations {file1} vs {file2}", result="Failed: File not found")
                return f"Error: One or both config files not found"
            with open(file1, 'r', encoding='utf-8') as f1, open(file2, 'r', encoding='utf-8') as f2:
                config1 = f1.readlines()
                config2 = f2.readlines()
            diff = difflib.unified_diff(config1, config2, fromfile=file1, tofile=file2)
            output = "".join(diff)
            result = self.log_action(f"Compare configurations {file1} vs {file2}")
            return output or "Configurations are identical"
        except Exception as e:
            result = self.log_action(f"Compare configurations {file1} vs {file2}", result=f"Failed: {str(e)}")
            return f"Error: {str(e)}"

    def schedule_backup(self, device_list: str, frequency: str) -> str:
        device_list = [ip.strip() for ip in device_list.split(",") if ip.strip()]
        if not device_list:
            result = self.log_action("Schedule backup", result="Failed: No devices specified")
            return "Error: No devices specified"
        try:
            def job():
                for ip in device_list:
                    self.backup_configuration(ip)
            if frequency.lower() == "daily":
                schedule.every().day.at("02:00").do(job)
            elif frequency.lower() == "weekly":
                schedule.every().monday.at("02:00").do(job)
            elif frequency.lower() == "monthly":
                schedule.every(30).days.at("02:00").do(job)
            else:
                result = self.log_action(f"Schedule backup for {device_list}", result="Failed: Invalid frequency")
                return f"Error: Invalid frequency {frequency}"
            def run_scheduler():
                while True:
                    schedule.run_pending()
                    time.sleep(60)
            threading.Thread(target=run_scheduler, daemon=True).start()
            result = self.log_action(f"Schedule backup for {device_list} with {frequency} frequency")
            return f"Backup scheduled for {device_list} with {frequency} frequency"
        except Exception as e:
            result = self.log_action(f"Schedule backup for {device_list}", result=f"Failed: {str(e)}")
            return f"Error: {str(e)}"

    def synchronize_time(self, reference_ip: str, devices: str) -> str:
        device_list = [ip.strip() for ip in devices.split(",") if ip.strip()]
        results = []
        for ip in device_list:
            connection = self.get_device_connection(ip)
            if not connection:
                results.append(f"{ip}: Error - Unable to connect")
                self.log_action(f"Synchronize time on {ip}", ip, "Failed")
                continue
            try:
                commands = [
                    f"ntp server {reference_ip}"
                ]
                output = connection.send_config_set(commands, delay_factor=2, max_loops=150)
                connection.save_config()
                results.append(f"{ip}:\n{output}")
                self.log_action(f"Synchronize time on {ip}", ip)
            except Exception as e:
                results.append(f"{ip}: Error - {str(e)}")
                self.log_action(f"Synchronize time on {ip}", ip, f"Failed: {str(e)}")
            finally:
                connection.disconnect()
        return "\n\n".join(results) if results else "No devices processed"

    def show_ntp_status(self, ip_address: str) -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            result = self.log_action(f"Show NTP status for {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            output = connection.send_command("show ntp status", expect_string=r"#", read_timeout=90)
            result = self.log_action(f"Show NTP status for {ip_address}", ip_address)
            return output or "No NTP status available"
        except Exception as e:
            result = self.log_action(f"Show NTP status for {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    def add_device(self, ip_address: str, username: str, password: str, secret: str = "", device_type: str = "cisco_ios", snmp_community: str = "public") -> str:
        self.device_credentials[ip_address] = {
            'username': username,
            'password': password,
            'secret': secret,
            'device_type': device_type,
            'snmp_community': snmp_community
        }
        self.save_config()
        result = self.log_action(f"Add/Update device {ip_address}")
        return f"Device {ip_address} added/updated successfully"

    def configure_ssh(self, ip_address: str, username: str, password: str) -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            result = self.log_action(f"Configure SSH on {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            commands = [
                f"username {username} privilege 15 password {password}",
                "ip domain-name local.domain",
                "crypto key generate rsa general-keys modulus 2048",
                "ip ssh version 2",
                "line vty 0 4",
                "transport input ssh",
                "login local"
            ]
            output = connection.send_config_set(commands, delay_factor=2, max_loops=500)
            connection.save_config()
            result = self.log_action(f"Configure SSH on {ip_address}", ip_address)
            return output
        except Exception as e:
            result = self.log_action(f"Configure SSH on {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()

    def configure_snmp(self, ip_address: str, community: str, access_type: str = "ro") -> str:
        connection = self.get_device_connection(ip_address)
        if not connection:
            result = self.log_action(f"Configure SNMP on {ip_address}", ip_address, "Failed")
            return f"Error: Unable to connect to {ip_address}"
        try:
            commands = [
                f"snmp-server community {community} {access_type}"
            ]
            output = connection.send_config_set(commands,read_timeout=60)
            connection.send_command("write memory",read_timeout=60)
            result = self.log_action(f"Configure SNMP on {ip_address}", ip_address)
            return output
        except Exception as e:
            result = self.log_action(f"Configure SNMP on {ip_address}", ip_address, f"Failed: {str(e)}")
            return f"Error: {str(e)}"
        finally:
            connection.disconnect()



        

    # Broadcast traps to connected WebSocket clients
    async def broadcast_trap(self, message: str):
        for client in self.trap_clients.copy():
            try:
                await client.send_text(message)
            except Exception:
                self.trap_clients.remove(client)

    def register_trap_client(self, websocket: WebSocket):
        self.trap_clients.append(websocket)
        print("✅ Registered WebSocket client")

    def unregister_trap_client(self, websocket: WebSocket):
        if websocket in self.trap_clients:
            self.trap_clients.remove(websocket)
            print("❌ Unregistered WebSocket client")

    def start_trap_receiver(self):
        """Start SNMP trap receiver in a separate thread."""
        def run_receiver():
            snmp_engine = engine.SnmpEngine()

            # SNMPv2c community
            config.addV1System(snmp_engine, 'my-area', self.default_snmp_community)

            # Listen on UDP port 1162
            config.addTransport(
                snmp_engine,
                udp.domainName,
                udp.UdpTransport().openServerMode(('0.0.0.0', 162))
            )
            print("🚀 Trap receiver starting...")

            # Callback for received traps
            def cb_fun(snmp_engine, state_reference, context_engine_id, context_name, var_binds, cb_ctx):
                trap_info = {
                    'source': str(state_reference).split(':')[-1],
                    'timestamp': datetime.now().isoformat(),
                    'var_binds': [(str(oid), str(value)) for oid, value in var_binds]
                }
                print("🔥 Trap received:", trap_info)

                # Broadcast to WebSocket clients
                if self.loop:
                    asyncio.run_coroutine_threadsafe(
                        self.broadcast_trap(json.dumps(trap_info)),
                        self.loop
                    )

            ntfrcv.NotificationReceiver(snmp_engine, cb_fun)

            print("🚀 Listening for SNMP traps on UDP 1162 ...")
            snmp_engine.transportDispatcher.jobStarted(1)
            try:
                snmp_engine.transportDispatcher.runDispatcher()
            except Exception as e:
                print("Trap receiver error:", e)

        threading.Thread(target=run_receiver, daemon=True).start()

