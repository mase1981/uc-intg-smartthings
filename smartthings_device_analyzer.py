#!/usr/bin/env python3
"""
SmartThings Device Analyzer - Standalone Script
No dependencies required beyond Python standard library

This script helps analyze SmartThings devices to improve integration support.
It connects to SmartThings API and outputs detailed device information.

:copyright: (c) 2025 by Meir Miyara
:license: MPL-2.0, see LICENSE for more details
"""

import json
import re
import sys
import ssl
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from typing import Dict, List, Any, Optional


class SmartThingsDeviceAnalyzer:
    """Standalone SmartThings device analyzer"""
    
    def __init__(self):
        self.base_url = "https://api.smartthings.com/v1"
        self.token = None
        
    def validate_token(self, token: str) -> bool:
        """Validate SmartThings Personal Access Token format"""
        if not token or not isinstance(token, str):
            return False
        
        # SmartThings PAT format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
        pattern = r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
        return bool(re.match(pattern, token.lower().strip()))
    
    def make_request(self, endpoint: str) -> Dict[str, Any]:
        """Make HTTP request to SmartThings API"""
        if not self.token:
            raise ValueError("No access token provided")
            
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json',
            'User-Agent': 'SmartThings-Device-Analyzer/1.0'
        }
        
        try:
            request = Request(url, headers=headers)
            
            # Create SSL context that works in most environments
            try:
                context = ssl.create_default_context()
            except Exception:
                context = ssl._create_unverified_context()
                
            with urlopen(request, context=context, timeout=30) as response:
                if response.status == 200:
                    return json.loads(response.read().decode('utf-8'))
                else:
                    raise HTTPError(
                        url, response.status, f"HTTP {response.status}", 
                        response.headers, None
                    )
                    
        except HTTPError as e:
            if e.code == 401:
                raise ValueError("Invalid or expired access token")
            elif e.code == 403:
                raise ValueError("Access token lacks required permissions")
            elif e.code == 429:
                raise ValueError("Rate limit exceeded. Please wait and try again.")
            else:
                raise ValueError(f"API Error {e.code}: {e.reason}")
        except URLError as e:
            raise ValueError(f"Network error: {e.reason}")
        except Exception as e:
            raise ValueError(f"Request failed: {str(e)}")
    
    def get_locations(self) -> List[Dict[str, Any]]:
        """Get SmartThings locations"""
        response = self.make_request("/locations")
        return response.get("items", [])
    
    def get_devices(self, location_id: str) -> List[Dict[str, Any]]:
        """Get devices for a location"""
        response = self.make_request(f"/devices?locationId={location_id}")
        return response.get("items", [])
    
    def get_rooms(self, location_id: str) -> List[Dict[str, Any]]:
        """Get rooms for a location"""
        response = self.make_request(f"/locations/{location_id}/rooms")
        return response.get("items", [])
    
    def analyze_device(self, device: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze a single device and extract relevant information"""
        analysis = {
            "device_id": device.get("deviceId", "unknown"),
            "name": device.get("label") or device.get("name", "Unknown Device"),
            "device_type": device.get("deviceTypeName", ""),
            "manufacturer": device.get("deviceManufacturerCode", ""),
            "room_id": device.get("roomId"),
            "location_id": device.get("locationId"),
            "capabilities": [],
            "raw_capabilities": {},
            "components": device.get("components", []),
            "full_device_data": device  # Include full data for debugging
        }
        
        # Extract capabilities
        for component in device.get("components", []):
            for capability in component.get("capabilities", []):
                cap_id = capability.get("id", "")
                if cap_id:
                    analysis["capabilities"].append(cap_id)
                    analysis["raw_capabilities"][cap_id] = capability
        
        # Remove duplicates while preserving order
        analysis["capabilities"] = list(dict.fromkeys(analysis["capabilities"]))
        
        return analysis
    
    def run_analysis(self):
        """Main analysis workflow"""
        print("=" * 60)
        print("SmartThings Device Analyzer")
        print("=" * 60)
        print()
        
        # Get access token
        while True:
            print("Please enter your SmartThings Personal Access Token:")
            print("(You can generate one at: https://account.smartthings.com/tokens)")
            token = input("Token: ").strip()
            
            if not token:
                print("❌ No token provided. Please try again.")
                continue
                
            if not self.validate_token(token):
                print("❌ Invalid token format. Expected format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
                continue
                
            self.token = token.lower()
            break
        
        print("\n🔍 Connecting to SmartThings API...")
        
        try:
            # Test connection and get locations
            locations = self.get_locations()
            
            if not locations:
                print("❌ No locations found in your SmartThings account.")
                return
            
            print(f"✅ Connected successfully! Found {len(locations)} location(s).")
            
            # Select location
            if len(locations) == 1:
                selected_location = locations[0]
                print(f"📍 Using location: {selected_location['name']}")
            else:
                print("\n📍 Available locations:")
                for i, location in enumerate(locations, 1):
                    print(f"  {i}. {location['name']}")
                
                while True:
                    try:
                        choice = int(input(f"\nSelect location (1-{len(locations)}): "))
                        if 1 <= choice <= len(locations):
                            selected_location = locations[choice - 1]
                            break
                        else:
                            print(f"Please enter a number between 1 and {len(locations)}")
                    except ValueError:
                        print("Please enter a valid number")
            
            location_id = selected_location["locationId"]
            location_name = selected_location["name"]
            
            print(f"\n🔍 Discovering devices in '{location_name}'...")
            
            # Get devices and rooms
            devices = self.get_devices(location_id)
            rooms = self.get_rooms(location_id)
            
            # Create room mapping
            room_map = {room["roomId"]: room["name"] for room in rooms}
            
            if not devices:
                print("❌ No devices found in this location.")
                return
            
            print(f"✅ Found {len(devices)} device(s)!")
            
            # Analyze all devices
            analysis_results = {
                "timestamp": self._get_timestamp(),
                "location": {
                    "id": location_id,
                    "name": location_name
                },
                "rooms": room_map,
                "device_count": len(devices),
                "devices": []
            }
            
            print("\n" + "=" * 60)
            print("DEVICE ANALYSIS RESULTS")
            print("=" * 60)
            
            for i, device in enumerate(devices, 1):
                analysis = self.analyze_device(device)
                analysis_results["devices"].append(analysis)
                
                room_name = room_map.get(analysis["room_id"], "No Room")
                
                print(f"\n📱 Device {i}: {analysis['name']}")
                print(f"   └─ ID: {analysis['device_id']}")
                print(f"   └─ Type: {analysis['device_type']}")
                print(f"   └─ Manufacturer: {analysis['manufacturer']}")
                print(f"   └─ Room: {room_name}")
                print(f"   └─ Capabilities ({len(analysis['capabilities'])}): {', '.join(analysis['capabilities'])}")
            
            # Generate output file
            output_filename = f"smartthings_analysis_{location_id[:8]}.json"
            
            print(f"\n💾 Saving detailed analysis to: {output_filename}")
            
            with open(output_filename, 'w', encoding='utf-8') as f:
                json.dump(analysis_results, f, indent=2, ensure_ascii=False)
            
            print("✅ Analysis complete!")
            print(f"\n📋 Summary:")
            print(f"   • Location: {location_name}")
            print(f"   • Total devices: {len(devices)}")
            print(f"   • Rooms: {len(rooms)}")
            print(f"   • Analysis file: {output_filename}")
            
            # Show problematic devices (if any)
            problem_devices = []
            for device_analysis in analysis_results["devices"]:
                if not device_analysis["capabilities"]:
                    problem_devices.append(device_analysis["name"])
            
            if problem_devices:
                print(f"\n⚠️  Devices with no capabilities detected:")
                for device_name in problem_devices:
                    print(f"   • {device_name}")
                print("   These devices might need special handling in the integration.")
            
            print(f"\n📧 Please share the '{output_filename}' file with the developer")
            print("   to improve device support in the UC Remote integration.")
            
        except ValueError as e:
            print(f"❌ Error: {e}")
        except KeyboardInterrupt:
            print("\n\n👋 Analysis cancelled by user.")
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
    
    def _get_timestamp(self) -> str:
        """Get current timestamp"""
        from datetime import datetime
        return datetime.now().isoformat()


def main():
    """Main entry point"""
    try:
        analyzer = SmartThingsDeviceAnalyzer()
        analyzer.run_analysis()
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()