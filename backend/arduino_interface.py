#!/usr/bin/env python3
"""
Arduino Integration Module - NEO Smart Grid
Handles serial communication with Arduino and power calculations
"""

import serial
import json
import time
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

@dataclass
class SensorData:
    """Sensor readings from Arduino"""
    sun: int  # 0-1023 LDR reading
    city_voltage: float  # Output voltage after relay
    grid_voltage: float  # Bench supply potential
    bmp_temperature: float  # BMP180 temperature
    humidity: float  # DHT11 humidity
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

class PowerCalculator:
    """Calculate power consumption and impact"""
    
    @staticmethod
    def calculate_consumption(
        brightness_red: float,
        brightness_yellow: float,
        brightness_green: float,
        brightness_white: float
    ) -> float:
        """
        Calculate LED power consumption (0.0-1.0)
        
        Brightness inputs: 0.0 to 1.0 (or pwm 0-255 scaled to 0-1)
        Returns: total consumption as fraction of max
        
        LED Power Distribution:
        - Red: 20.4%
        - Yellow: 39.6%
        - Green: 31.8%
        - White: 7.7%
        """
        return (
            0.204 * brightness_red +
            0.396 * brightness_yellow +
            0.318 * brightness_green +
            0.077 * brightness_white
        )
    
    @staticmethod
    def calculate_power_from_voltage(voltage: float, shunt_resistance: float = 0.1) -> float:
        """
        Calculate current from voltage drop over shunt resistor
        Power = V^2 / R where V is (5V - measured_voltage_drop)
        
        Args:
            voltage: Measured voltage (0-5V range)
            shunt_resistance: Shunt resistor value in ohms
        
        Returns: Power in watts
        """
        if voltage >= 5.0:
            return 0.0  # No current, no power
        
        voltage_drop = 5.0 - voltage
        current = voltage_drop / shunt_resistance
        load_resistance = 50.0  # ohms
        power = (voltage_drop ** 2) / load_resistance
        return power
    
    @staticmethod
    def calculate_solar_generation(light_reading: int) -> float:
        """
        Estimate solar generation from light sensor
        0-1023 ADC reading maps to 0-800mA
        """
        return (light_reading / 1023.0) * 800.0

class ArduinoInterface:
    """Handles serial communication with Arduino"""
    
    def __init__(self, port: str = "COM3", baud: int = 115200, timeout: float = 1.0):
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.serial = None
        self.connected = False
        self.current_pwm = [204] * 16  # 80% default
        self.relay_state = False
    
    def connect(self) -> bool:
        """Connect to Arduino"""
        try:
            self.serial = serial.Serial(self.port, self.baud, timeout=self.timeout)
            time.sleep(2)  # Wait for Arduino reset
            self.connected = True
            print(f"[ARDUINO] Connected on {self.port} @ {self.baud} baud")
            return True
        except Exception as e:
            print(f"[ARDUINO] Connection failed: {e}")
            self.connected = False
            return False
    
    def read_telemetry(self) -> Optional[SensorData]:
        """
        Read and parse telemetry from Arduino
        Expected format: SUN:xxx|CITY_V:x.xx|GRID_V:x.xx|BMP_T:x.x|HUM:x.x
        """
        if not self.connected or not self.serial:
            return None
        
        try:
            line = self.serial.readline().decode("utf-8", errors="replace").strip()
            if not line or line.startswith("EVENT:"):
                return None
            
            if "|" not in line:
                return None
            
            fields = {}
            for field in line.split("|"):
                if ":" in field:
                    key, val = field.split(":", 1)
                    try:
                        fields[key] = float(val)
                    except ValueError:
                        pass
            
            # Validate required fields
            required = ["SUN", "CITY_V", "GRID_V", "BMP_T", "HUM"]
            if not all(k in fields for k in required):
                return None
            
            return SensorData(
                sun=int(fields["SUN"]),
                city_voltage=fields["CITY_V"],
                grid_voltage=fields["GRID_V"],
                bmp_temperature=fields["BMP_T"],
                humidity=fields["HUM"]
            )
        
        except Exception as e:
            print(f"[ARDUINO] Parse error: {e}")
            return None
    
    def send_command(self, pwm_values: list, relay: int, lcd_line1: str = "", lcd_line2: str = "") -> bool:
        """
        Send control command to Arduino
        
        Format: PWM:v0,v1,...,v15,RELAY:r,LCD1:text,LCD2:text\n
        """
        if not self.connected or not self.serial:
            return False
        
        if len(pwm_values) != 16:
            print(f"[ARDUINO] Invalid PWM count: {len(pwm_values)} (expected 16)")
            return False
        
        if relay not in (0, 1):
            print(f"[ARDUINO] Invalid relay value: {relay}")
            return False
        
        try:
            pwm_str = ",".join(str(int(max(0, min(255, v)))) for v in pwm_values)
            lcd1 = lcd_line1[:16].ljust(16)
            lcd2 = lcd_line2[:16].ljust(16)
            
            command = f"PWM:{pwm_str},RELAY:{relay},LCD1:{lcd1},LCD2:{lcd2}\n"
            
            self.serial.write(command.encode("utf-8"))
            self.current_pwm = pwm_values
            self.relay_state = bool(relay)
            
            return True
        
        except Exception as e:
            print(f"[ARDUINO] Send error: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from Arduino"""
        if self.serial and self.connected:
            try:
                self.serial.close()
                self.connected = False
                print("[ARDUINO] Disconnected")
            except Exception as e:
                print(f"[ARDUINO] Disconnect error: {e}")

class PowerAllocationEngine:
    """Intelligently allocate power based on sensor data and priorities"""
    
    def __init__(self):
        self.zones = {
            "T1": {"name": "Hospitals", "channels": [0, 1], "protected": True},
            "T2": {"name": "Utilities", "channels": [2, 3, 4], "protected": False},
            "T3": {"name": "Industrial", "channels": [5, 6, 7, 8, 9], "protected": False},
            "T4": {"name": "Commercial", "channels": [10, 11, 12, 13, 14, 15], "protected": False},
        }
    
    def allocate_power(
        self,
        sensor_data: SensorData,
        solar_ma: float,
        load_ma: float,
        directive: Optional[str] = None
    ) -> Tuple[list, str]:
        """
        Allocate power across zones based on sensor data and optional directive
        
        Returns: (pwm_values, explanation)
        """
        pwm = [204] * 16  # Start at 80% default
        
        # Parse directive intent
        if directive:
            directive_lower = directive.lower()
            
            if any(w in directive_lower for w in ['off', 'shutdown', 'emergency', 'reduce', 'save']):
                # REDUCE mode: minimize consumption
                pwm[0:2] = [255, 255]    # T1 hospitals always full
                pwm[2:5] = [102, 102, 102]  # T2 utilities 40%
                pwm[5:10] = [51, 51, 51, 51, 51]  # T3 industrial 20%
                pwm[10:16] = [0, 0, 0, 0, 0, 0]   # T4 commercial OFF
                
                total_load = 2*255 + 3*102 + 5*51  # Estimate
                explanation = f"POWER DEFICIT MODE | Reducing allocation to match {load_ma:.0f}mA demand"
                
            elif any(w in directive_lower for w in ['maximize', 'full', 'export', 'charge']):
                # INCREASE mode: maximize generation/export
                pwm = [230] * 16  # 90% across board
                pwm[0:2] = [255, 255]    # T1 hospitals always full
                pwm[10:16] = [255, 255, 255, 255, 255, 255]  # T4 commercial FULL for export
                
                explanation = f"POWER EXPORT MODE | Maximizing generation at {solar_ma:.0f}mA solar output"
            
            else:
                # BALANCED: maintain current allocations
                explanation = f"BALANCED MODE | Solar: {solar_ma:.0f}mA vs Load: {load_ma:.0f}mA"
        
        else:
            # No directive - auto allocate based on available solar
            battery_ratio = 0.5  # Assume 50% battery
            
            if solar_ma > load_ma * 1.5:
                # Excess solar - increase all zones
                pwm = [220] * 16
                pwm[0:2] = [255, 255]
                explanation = f"SOLAR SURPLUS | Excess generation available: {solar_ma - load_ma:.0f}mA extra"
            
            elif solar_ma > load_ma:
                # Balanced
                pwm = [200] * 16
                pwm[0:2] = [255, 255]
                explanation = f"BALANCED | Solar matches demand: {solar_ma:.0f}mA = {load_ma:.0f}mA"
            
            else:
                # Solar deficit - reduce non-critical
                pwm[0:2] = [255, 255]    # T1 hospitals full
                pwm[2:5] = [180, 180, 180]  # T2 utilities 70%
                pwm[5:10] = [140, 140, 140, 140, 140]  # T3 industrial 55%
                pwm[10:16] = [100, 100, 100, 100, 100, 100]  # T4 commercial 40%
                
                deficit = load_ma - solar_ma
                explanation = f"SOLAR DEFICIT | {deficit:.0f}mA shortfall, reducing T4 commercial"
        
        return pwm, explanation

if __name__ == "__main__":
    # Test calculations
    calc = PowerCalculator()
    
    # Test LED consumption
    consumption = calc.calculate_consumption(0.8, 0.9, 0.85, 0.5)
    print(f"LED Consumption: {consumption*100:.1f}%")
    
    # Test solar generation
    solar = calc.calculate_solar_generation(800)
    print(f"Solar Generation: {solar:.0f}mA")
    
    # Test Arduino interface
    arduino = ArduinoInterface(port="COM3")
    print(f"Arduino interface ready (not connected yet)")
