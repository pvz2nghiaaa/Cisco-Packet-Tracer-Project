#!/usr/bin/env python3
import xml.etree.ElementTree as ET
import copy
import subprocess
import os
import uuid
import sys

def merge_topologies(main_path, floor34_path, output_path):
    print(f"Loading main topology XML: {main_path}...")
    tree_main = ET.parse(main_path)
    root_main = tree_main.getroot()
    
    print(f"Loading floor34 topology XML: {floor34_path}...")
    tree_floor34 = ET.parse(floor34_path)
    root_floor34 = tree_floor34.getroot()
    
    # 1. UUID Mappings for physical containers and overlapping device physical nodes
    # Main physical UUIDs -> Floor34 physical UUIDs (aligning with Packet Tracer 9.0 format)
    uuid_mapping = {
        "{f5f90242-1793-423e-8feb-9bdb51eb9990}": "{67b16e03-66dd-40c0-be35-303d4b67254b}", # Intercity
        "{3efcb985-a15e-45fc-a20f-c82a39e95d32}": "{69f9f8f6-3be6-4b2f-9c92-74e054bbfd1b}", # Home City
        "{8120e552-3384-4660-83df-dc9a15d4fdbe}": "{3b6b83e5-f000-4752-b28a-77e8125ed574}", # Corporate Office
        "{26f1fad4-c0e5-443c-8676-588c31c51759}": "{b8bc7c17-2ea7-450c-b071-8e3036fb7c7f}", # Main Wiring Closet
        "{e5c2e8f1-eeba-43df-819d-3859a32f5f74}": "{a70d9f51-2a6e-4855-af2e-4d09175b8679}", # Rack
        "{782c572b-41c4-4a68-85d6-2c009643448f}": "{a2c7aace-fa1a-4eb1-8a37-254b306e462c}", # R1 physical UUID
        "{9ca12033-1bff-4962-81ab-d9f767a996a6}": "{9b839b09-9221-41a7-bcd3-2c8611a24a2c}", # R2 physical UUID
    }
    
    # Rack slots mapping to prevent physical device overlaps in the Rack
    rack_shifts = {
        'SW-HC': 44,
        'Access Point0': 52,
        'SW-KT': 56,
        'SW-LD': 60
    }
    
    # 2. Get device elements
    devices_main = root_main.find('.//NETWORK/DEVICES')
    devices_floor34 = root_floor34.find('.//NETWORK/DEVICES')
    
    # Overlapping devices that we will handle specifically
    overlapping_names = {'R1', 'R2', 'Power Distribution Device0'}
    
    # Rebuild DEVICES starting with floor34's devices
    # Remove R1 and R2 from floor34 devices, but keep Power Distribution Device0 from floor34
    merged_devices = []
    for d in devices_floor34:
        name = d.find('.//ENGINE/NAME').text
        if name not in {'R1', 'R2'}:
            merged_devices.append(d)
            
    # Add unique devices from main, plus R1 and R2 from main
    for d in devices_main:
        name = d.find('.//ENGINE/NAME').text
        if name != 'Power Distribution Device0':
            d_copy = copy.deepcopy(d)
            
            # Update physical path and container in WORKSPACE/PHYSICAL_CPUR
            phys = d_copy.find('.//WORKSPACE/PHYSICAL_CPUR')
            if phys is not None:
                parent_path_el = phys.find('PARENT_PATH')
                if parent_path_el is not None and parent_path_el.text:
                    parts = parent_path_el.text.split(',')
                    new_parts = [uuid_mapping.get(p, p) for p in parts]
                    parent_path_el.text = ",".join(new_parts)
                
                container_id_el = phys.find('CONTAINER_ID')
                if container_id_el is not None and container_id_el.text:
                    container_id_el.text = uuid_mapping.get(container_id_el.text, container_id_el.text)
                    
                # Shift X coordinate if it is in rack_shifts
                if name in rack_shifts:
                    new_x = str(rack_shifts[name])
                    phys.find('X').text = new_x
                    
                # Add version 9.0 cpur tags if missing
                if phys.find('ICP_CONTAINER_SCENE_X') is None:
                    icp_csx = ET.Element('ICP_CONTAINER_SCENE_X')
                    icp_csx.text = '0'
                    phys.append(icp_csx)
                if phys.find('ICP_CONTAINER_SCENE_Y') is None:
                    icp_csy = ET.Element('ICP_CONTAINER_SCENE_Y')
                    icp_csy.text = '0'
                    phys.append(icp_csy)
                if phys.find('ORIGINAL_DEVICE_UUID') is None:
                    orig_uuid_el = ET.Element('ORIGINAL_DEVICE_UUID')
                    orig_uuid_el.text = f"{{{str(uuid.uuid4())}}}"
                    phys.append(orig_uuid_el)
            
            # Update PHYSICAL path tag under WORKSPACE (crucial version 9.0 mapping fix!)
            workspace = d_copy.find('.//WORKSPACE')
            if workspace is not None:
                physical_el = workspace.find('PHYSICAL')
                if physical_el is not None and physical_el.text:
                    parts = physical_el.text.split(',')
                    new_parts = [uuid_mapping.get(p, p) for p in parts]
                    physical_el.text = ",".join(new_parts)
            
            # If name is R1 or R2, update their hostnames to match floor34 configuration
            if name in {'R1', 'R2'}:
                sys_name_el = d_copy.find('.//ENGINE/SYS_NAME')
                if sys_name_el is not None:
                    sys_name_el.text = name
                rc = d_copy.find('.//RUNNINGCONFIG')
                if rc is not None:
                    for line in rc.findall('LINE'):
                        if line.text and line.text.strip() == 'hostname Router':
                            line.text = f'hostname {name}'
                            
            merged_devices.append(d_copy)
            
    # Set the merged devices into root_floor34
    devices_floor34.clear()
    for d in merged_devices:
        devices_floor34.append(d)
        
    print(f"Merged logical devices count: {len(devices_floor34)}")
    
    # 3. Merge physical node hierarchies in PHYSICALWORKSPACE
    def find_node_by_uuid(node, uuid):
        uuid_el = node.find('UUID_STR')
        if uuid_el is not None and uuid_el.text == uuid:
            return node
        children_el = node.find('CHILDREN')
        if children_el is not None:
            for child in children_el.findall('NODE'):
                res = find_node_by_uuid(child, uuid)
                if res is not None:
                    return res
        return None

    node_main = root_main.find('.//PHYSICALWORKSPACE/NODE')
    node_floor34 = root_floor34.find('.//PHYSICALWORKSPACE/NODE')
    
    # Find Main's Rack and Office
    rack_main = find_node_by_uuid(node_main, "{e5c2e8f1-eeba-43df-819d-3859a32f5f74}")
    office_main = find_node_by_uuid(node_main, "{8120e552-3384-4660-83df-dc9a15d4fdbe}")
    
    # Find Floor34's Rack and Office
    rack_floor34 = find_node_by_uuid(node_floor34, "{a70d9f51-2a6e-4855-af2e-4d09175b8679}")
    office_floor34 = find_node_by_uuid(node_floor34, "{3b6b83e5-f000-4752-b28a-77e8125ed574}")
    
    rack_main_children = rack_main.find('CHILDREN')
    office_main_children = office_main.find('CHILDREN')
    
    rack_floor34_children = rack_floor34.find('CHILDREN')
    office_floor34_children = office_floor34.find('CHILDREN')
    
    # Copy devices from main's Rack to floor34's Rack (except R1, R2, Power strip)
    for child in list(rack_main_children.findall('NODE')):
        name = child.find('NAME').text
        ntype = child.find('TYPE').text
        if ntype == '6' and name not in {'R1', 'R2', 'Power Distribution Device0'}:
            print(f"Copying physical rack node: {name}")
            child_copy = copy.deepcopy(child)
            
            # Shift X coordinate to prevent rack slot collision
            if name in rack_shifts:
                new_x = str(rack_shifts[name])
                print(f"  Shifting rack position to X={new_x}")
                child_copy.find('X').text = new_x
                
            # Add version 9.0 physical nodes tags (ICP_CSX / ICP_CSY)
            if child_copy.find('ICP_CSX') is None:
                icp_x = ET.Element('ICP_CSX')
                icp_x.text = '0'
                child_copy.append(icp_x)
            if child_copy.find('ICP_CSY') is None:
                icp_y = ET.Element('ICP_CSY')
                icp_y.text = '0'
                child_copy.append(icp_y)
            
            rack_floor34_children.append(child_copy)
            
    # Copy devices from main's Office to floor34's Office
    for child in list(office_main_children.findall('NODE')):
        name = child.find('NAME').text
        ntype = child.find('TYPE').text
        if ntype == '6':
            print(f"Copying physical office node: {name}")
            child_copy = copy.deepcopy(child)
            
            # Add version 9.0 physical nodes tags (ICP_CSX / ICP_CSY)
            if child_copy.find('ICP_CSX') is None:
                icp_x = ET.Element('ICP_CSX')
                icp_x.text = '0'
                child_copy.append(icp_x)
            if child_copy.find('ICP_CSY') is None:
                icp_y = ET.Element('ICP_CSY')
                icp_y.text = '0'
                child_copy.append(icp_y)
            
            office_floor34_children.append(child_copy)
            
    # 4. Merge links in NETWORK/LINKS
    links_main = root_main.find('.//NETWORK/LINKS')
    links_floor34 = root_floor34.find('.//NETWORK/LINKS')
    
    merged_links = []
    for link in links_floor34:
        merged_links.append(copy.deepcopy(link))
    for link in links_main:
        merged_links.append(copy.deepcopy(link))
        
    links_floor34.clear()
    for link in merged_links:
        links_floor34.append(link)
        
    print(f"Merged links count: {len(links_floor34)}")
    
    # Convert tree to XML string
    xml_str = ET.tostring(root_floor34, encoding='utf-8')
    
    # 5. Global ID Replacements for router reference alignments
    replacements = [
        (b'save-ref-id:5007223063351866022', b'save-ref-id:7316120762633091324'), # R1 ref id
        (b'save-ref-id:1826725449005225424', b'save-ref-id:4657625167426509667'), # R2 ref id
        (b'52310463544', b'1673172766464'), # R1 DEV_ADDR
        (b'52308530232', b'1673224901808'), # R2 DEV_ADDR
    ]
    
    for old_val, new_val in replacements:
        xml_str = xml_str.replace(old_val, new_val)
        
    print(f"Writing merged XML topology to {output_path}...")
    with open(output_path, 'wb') as f:
        f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str)
        
    print("Merge completed successfully!")

if __name__ == '__main__':
    if len(sys.argv) < 4:
        print("Usage: py merge_topologies.py <main_decoded.xml> <floor34_decoded.xml> <output.xml>")
        sys.exit(1)
        
    merge_topologies(sys.argv[1], sys.argv[2], sys.argv[3])
