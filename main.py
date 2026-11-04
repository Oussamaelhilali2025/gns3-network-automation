
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import os
import asyncio
import datetime
import json
from network_automation import InteractiveNetworkAutomation
import logging
from fastapi import WebSocket, WebSocketDisconnect
from contextlib import asynccontextmanager

automation = InteractiveNetworkAutomation()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    automation.loop = asyncio.get_running_loop()
    automation.start_trap_receiver()
    yield


app = FastAPI(title="GNS3 Network Automation",lifespan=lifespan)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize automation instance
automation = InteractiveNetworkAutomation()

# Pydantic models for request validation
class DeviceRequest(BaseModel):
    ip_address: str

class CustomCommandRequest(BaseModel):
    ip_address: str
    command: str

class InterfaceIPRequest(BaseModel):
    ip_address: str
    interface: str
    ip_addr: str
    subnet_mask: str

class LoopbackRequest(BaseModel):
    ip_address: str
    loopback_num: int
    loopback_ip: str
    subnet_mask: Optional[str] = "255.255.255.255"

class DHCPRequest(BaseModel):
    ip_address: str
    pool_name: str
    network: str
    subnet_mask: str
    default_router: str
    dns_server: Optional[str] = ""

class InterfaceToggleRequest(BaseModel):
    ip_address: str
    interface: str
    action: str

class StaticRouteRequest(BaseModel):
    ip_address: str
    dest_network: str
    subnet_mask: str
    next_hop: str
    admin_distance: Optional[str] = ""

class OSPFRequest(BaseModel):
    ip_address: str
    process_id: int
    router_id: str
    network: str
    wildcard: str
    area: int

class EIGRPRequest(BaseModel):
    ip_address: str
    as_number: int
    network: str
    wildcard: str

class BGPRequest(BaseModel):
    ip_address: str
    as_number: int
    router_id: str
    neighbor_ip: str
    neighbor_as: int

class VLANRequest(BaseModel):
    ip_address: str
    vlan_id: int
    vlan_name: str

class VLANPortRequest(BaseModel):
    ip_address: str
    interface: str
    vlan_id: int

class TrunkRequest(BaseModel):
    ip_address: str
    interface: str
    allowed_vlans: str

class PingSweepRequest(BaseModel):
    network: str
    start_ip: int
    end_ip: int

class PortScanRequest(BaseModel):
    ip_address: str
    ports: str

class SNMPRequest(BaseModel):
    ip_address: str
    community: Optional[str] = "public"

class TopologyRequest(BaseModel):
    seed_ip: str

class MultiDeviceCommandRequest(BaseModel):
    devices: str
    command: str

class BulkConfigRequest(BaseModel):
    devices: str
    commands: str

class NetworkVLANRequest(BaseModel):
    switches: str
    vlan_id: int
    vlan_name: str

class MassInterfaceRequest(BaseModel):
    ip_address: str
    interfaces: str
    template: str
    vlan_id: Optional[int] = None
    allowed_vlans: Optional[str] = None
    ip_addr: Optional[str] = None
    subnet_mask: Optional[str] = None
    commands: Optional[str] = None

class BackupRequest(BaseModel):
    ip_address: str

class RestoreRequest(BaseModel):
    ip_address: str
    config_file: str

class CompareRequest(BaseModel):
    file1: str
    file2: str

class ScheduleBackupRequest(BaseModel):
    device_list: str
    frequency: str

class NTPSyncRequest(BaseModel):
    reference_ip: str
    devices: str

class NTPStatusRequest(BaseModel):
    ip_address: str

class AddDeviceRequest(BaseModel):
    ip_address: str
    username: str
    password: str
    secret: Optional[str] = ""
    device_type: Optional[str] = "cisco_ios"
    snmp_community: Optional[str] = "public"

class SSHConfigRequest(BaseModel):
    ip_address: str
    username: str
    password: str

class SNMPConfigRequest(BaseModel):
    ip_address: str
    community: str
    access_type: Optional[str] = "ro"

class DEVICERessource(BaseModel):
    ip_address: str

# API endpoints
@app.get("/")
async def root():
    return {"message": "GNS3 Network Automation API"}

@app.post("/api/set_current_device")
async def set_current_device(request: DeviceRequest):
    try:
        result = automation.set_current_device(request.ip_address)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error setting current device: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/test_connectivity")
async def test_connectivity(request: DeviceRequest):
    try:
        result = await automation.test_connectivity(request.ip_address)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error testing connectivity: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/show_device_info")
async def show_device_info(request: DeviceRequest):
    try:
        result = automation.show_device_info(request.ip_address)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error showing device info: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/execute_custom_command")
async def execute_custom_command(request: CustomCommandRequest):
    try:
        result = automation.execute_custom_command(request.ip_address, request.command)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error executing custom command: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/show_interface_status")
async def show_interface_status(request: DeviceRequest):
    try:
        result = automation.show_interface_status(request.ip_address)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error showing interface status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/configure_interface_ip")
async def configure_interface_ip(request: InterfaceIPRequest):
    try:
        result = automation.configure_interface_ip(request.ip_address, request.interface, request.ip_addr, request.subnet_mask)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error configuring interface IP: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/show_ip_configuration")
async def show_ip_configuration(request: DeviceRequest):
    try:
        result = automation.show_ip_configuration(request.ip_address)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error showing IP configuration: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/configure_loopback")
async def configure_loopback(request: LoopbackRequest):
    try:
        result = automation.configure_loopback(request.ip_address, request.loopback_num, request.loopback_ip, request.subnet_mask)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error configuring loopback: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/configure_dhcp_pool")
async def configure_dhcp_pool(request: DHCPRequest):
    try:
        result = automation.configure_dhcp_pool(request.ip_address, request.pool_name, request.network, request.subnet_mask, request.default_router, request.dns_server)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error configuring DHCP pool: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/toggle_interface")
async def toggle_interface(request: InterfaceToggleRequest):
    try:
        result = automation.toggle_interface(request.ip_address, request.interface, request.action)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error toggling interface: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/configure_static_route")
async def configure_static_route(request: StaticRouteRequest):
    try:
        result = automation.configure_static_route(request.ip_address, request.dest_network, request.subnet_mask, request.next_hop, request.admin_distance)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error configuring static route: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/show_routing_table")
async def show_routing_table(request: DeviceRequest):
    try:
        result = automation.show_routing_table(request.ip_address)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error showing routing table: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/configure_ospf")
async def configure_ospf(request: OSPFRequest):
    try:
        result = automation.configure_ospf(request.ip_address, request.process_id, request.router_id, request.network, request.wildcard, request.area)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error configuring OSPF: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/configure_eigrp")
async def configure_eigrp(request: EIGRPRequest):
    try:
        result = automation.configure_eigrp(request.ip_address, request.as_number, request.network, request.wildcard)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error configuring EIGRP: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/configure_bgp")
async def configure_bgp(request: BGPRequest):
    try:
        result = automation.configure_bgp(request.ip_address, request.as_number, request.router_id, request.neighbor_ip, request.neighbor_as)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error configuring BGP: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/show_routing_protocols")
async def show_routing_protocols(request: DeviceRequest):
    try:
        result = automation.show_routing_protocols(request.ip_address)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error showing routing protocols: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/create_vlan")
async def create_vlan(request: VLANRequest):
    try:
        result = automation.create_vlan(request.ip_address, request.vlan_id, request.vlan_name)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error creating VLAN: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/show_vlan_info")
async def show_vlan_info(request: DeviceRequest):
    try:
        result = automation.show_vlan_info(request.ip_address)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error showing VLAN info: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/assign_port_to_vlan")
async def assign_port_to_vlan(request: VLANPortRequest):
    try:
        result = automation.assign_port_to_vlan(request.ip_address, request.interface, request.vlan_id)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error assigning port to VLAN: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/configure_trunk_port")
async def configure_trunk_port(request: TrunkRequest):
    try:
        result = automation.configure_trunk_port(request.ip_address, request.interface, request.allowed_vlans)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error configuring trunk port: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/delete_vlan")
async def delete_vlan(request: VLANRequest):
    try:
        result = automation.delete_vlan(request.ip_address, request.vlan_id)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error deleting VLAN: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/show_vlan_database")
async def show_vlan_database(request: DeviceRequest):
    try:
        result = automation.show_vlan_database(request.ip_address)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error showing VLAN database: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ping_sweep")
async def ping_sweep(request: PingSweepRequest):
    try:
        result = await automation.ping_sweep(request.network, request.start_ip, request.end_ip)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error performing ping sweep: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/port_scan")
async def port_scan(request: PortScanRequest):
    try:
        result = await automation.port_scan(request.ip_address, request.ports)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error performing port scan: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/snmp_discovery")
async def snmp_discovery(request: SNMPRequest):
    try:
        result = await automation.snmp_discovery(
            request.ip_address,
            request.community
        )
        return {"output": result}
    except Exception as e:
        logger.error(f"Error in SNMP discovery: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/show_neighbors")
async def show_neighbors(request: DeviceRequest):
    try:
        result = automation.show_neighbors(request.ip_address)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error showing neighbors: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/discover_topology")
async def discover_topology(request: TopologyRequest):
    try:
        result = automation.discover_topology(request.seed_ip)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error discovering topology: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/multi_device_command")
async def multi_device_command(request: MultiDeviceCommandRequest):
    try:
        result = automation.multi_device_command(request.devices, request.command)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error executing multi-device command: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/bulk_configuration")
async def bulk_configuration(request: BulkConfigRequest):
    try:
        result = automation.bulk_configuration(request.devices, request.commands)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error performing bulk configuration: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/network_wide_vlan")
async def network_wide_vlan(request: NetworkVLANRequest):
    try:
        result = automation.network_wide_vlan(request.switches, request.vlan_id, request.vlan_name)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error configuring network-wide VLAN: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/mass_interface_config")
async def mass_interface_config(request: MassInterfaceRequest):
    try:
        result = automation.mass_interface_config(
            request.ip_address, request.interfaces, request.template,
            request.vlan_id, request.allowed_vlans, request.ip_addr, request.subnet_mask, request.commands
        )
        return {"output": result}
    except Exception as e:
        logger.error(f"Error performing mass interface config: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/backup_configuration")
async def backup_configuration(request: BackupRequest):
    try:
        result = automation.backup_configuration(request.ip_address)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error backing up configuration: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/restore_configuration")
async def restore_configuration(request: RestoreRequest):
    try:
        result = automation.restore_configuration(request.ip_address, request.config_file)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error restoring configuration: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/compare_configurations")
async def compare_configurations(request: CompareRequest):
    try:
        result = automation.compare_configurations(request.file1, request.file2)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error comparing configurations: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/schedule_backup")
async def schedule_backup(request: ScheduleBackupRequest):
    try:
        result = automation.schedule_backup(request.device_list, request.frequency)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error scheduling backup: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/show_session_history")
async def show_session_history():
    try:
        result = automation.show_session_history()
        return {"output": result}
    except Exception as e:
        logger.error(f"Error showing session history: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/current_device")
async def get_current_device():
    try:
        return {"current_device": automation.current_device or "None Selected"}
    except Exception as e:
        logger.error(f"Error getting current device: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/synchronize_time")
async def synchronize_time(request: NTPSyncRequest):
    try:
        result = automation.synchronize_time(request.reference_ip, request.devices)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error synchronizing time: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/show_ntp_status")
async def show_ntp_status(request: NTPStatusRequest):
    try:
        result = automation.show_ntp_status(request.ip_address)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error showing NTP status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/add_device")
async def add_device(request: AddDeviceRequest):
    try:
        result = automation.add_device(
            request.ip_address,
            request.username,
            request.password,
            request.secret,
            request.device_type,
            request.snmp_community
        )
        return {"output": result}
    except Exception as e:
        logger.error(f"Error adding device: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/configure_ssh")
async def configure_ssh(request: SSHConfigRequest):
    try:
        result = automation.configure_ssh(request.ip_address, request.username, request.password)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error configuring SSH: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/configure_snmp")
async def configure_snmp(request: SNMPConfigRequest):
    try:
        result = automation.configure_snmp(
            request.ip_address,
            request.community,
            request.access_type
        )
        return {"output": result}
    except Exception as e:
        logger.error(f"Error configuring SNMP: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/system_resources")
async def system_resources(request: DEVICERessource):
    try:
        result = automation.system_resources(request.ip_address)
        return {"output": result}
    except Exception as e:
        logger.error(f"Error Resource for this device {request.ip_address}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))




@app.websocket("/ws/traps")
async def websocket_traps(websocket: WebSocket):
    await websocket.accept()
    automation.register_trap_client(websocket)
    try:
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        automation.unregister_trap_client(websocket)