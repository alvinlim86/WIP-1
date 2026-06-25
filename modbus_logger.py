import time
import glob
import sys
import os
import struct
import pandas as pd
from pymodbus.client import ModbusSerialClient
from pymodbus.exceptions import ModbusException

def auto_search_com_ports(max_ports: int = 5) -> list:
    """Scans the system for available COM/Serial ports."""
    if sys.platform.startswith('win'):
        ports = [f'COM{i}' for i in range(1, 256)]
    elif sys.platform.startswith('linux') or sys.platform.startswith('cygwin'):
        ports = glob.glob('/dev/ttyUSB*') + glob.glob('/dev/ttyS*') + glob.glob('/dev/ttyACM*')
    elif sys.platform.startswith('darwin'):
        ports = glob.glob('/dev/tty.usbserial*') or glob.glob('/dev/tty.usbmodem*')
    else:
        return []

    available_ports = []
    for port in ports:
        try:
            import serial
            s = serial.Serial(port)
            s.close()
            available_ports.append(port)
        except Exception:
            pass
        if len(available_ports) >= max_ports:
            break
    return available_ports

def process_modbus_registers(registers: list, endian_format: str = "ABCD") -> list:
    """Swaps 16-bit Modbus registers to match target endianness formats."""
    endian_format = endian_format.upper()
    processed = list(registers)
    for i in range(0, len(processed) - 1, 2):
        reg1, reg2 = processed[i], processed[i+1]
        a, b = (reg1 >> 8) & 0xFF, reg1 & 0xFF
        c, d = (reg2 >> 8) & 0xFF, reg2 & 0xFF
        
        if endian_format == "ABCD": continue
        elif endian_format == "BADC": processed[i], processed[i+1] = (b << 8) | a, (d << 8) | c
        elif endian_format == "CDAB": processed[i], processed[i+1] = (c << 8) | d, (a << 8) | b
        elif endian_format == "DCBA": processed[i], processed[i+1] = (d << 8) | c, (b << 8) | a
    return processed

def decode_registers_to_floats(registers: list) -> dict:
    """Unpacks 16-bit integers into raw values and IEEE 754 32-bit float pairs."""
    data_dict = {f'Reg_{i}': val for i, val in enumerate(registers)}
    for i in range(0, len(registers) - 1, 2):
        reg1, reg2 = registers[i], registers[i+1]
        if reg1 is None or reg2 is None:
            data_dict[f'Float32_{i}_{i+1}'] = None
            continue
        try:
            raw_bytes = struct.pack('>HH', reg1, reg2)
            data_dict[f'Float32_{i}_{i+1}'] = round(struct.unpack('>f', raw_bytes), 4)
        except Exception:
            data_dict[f'Float32_{i}_{i+1}'] = None
    return data_dict

def start_modbus_logger(
    file_name: str = "modbus_log", 
    num_addresses: int = 8, 
    interval_seconds: float = 10.0, 
    max_com_search: int = 5,
    slave_id: int = 1,
    baudrate: int = 9600,
    swap_strategy: str = "ABCD",
    total_days: float = 30.0
):
    """Modbus RTU Logger designed for clean terminal execution inside VS Code."""
    clean_base_name = file_name.replace('.csv', '')
    start_time_anchor = pd.Timestamp.now()
    start_time_str = start_time_anchor.strftime('%Y%m%d_%H%M%S')
    output_csv_path = f"{clean_base_name}_{start_time_str}.csv"
    stop_time_threshold = start_time_anchor + pd.Timedelta(days=total_days)

    available_ports = auto_search_com_ports(max_ports=max_com_search)
    chosen_port = available_ports if available_ports else "COM_SIMULATED"
    if chosen_port == "COM_SIMULATED":
        print("⚠️ Running in SIMULATION mode.")

    client = ModbusSerialClient(port=chosen_port, baudrate=baudrate, parity='N', stopbits=1, bytesize=8, timeout=1.5)
    print(f"Streaming data points directly to: {output_csv_path}")
    print("Press 'Ctrl + C' inside the VS Code terminal to stop execution early.\n")

    try:
        while True:
            current_timestamp = pd.Timestamp.now()
            
            # 1. Global Timeout Deadline Check
            if current_timestamp >= stop_time_threshold:
                print(f"\n🛑 Target operational run length achieved ({total_days} Days limit hit). Finalizing.")
                break

            # 2. Read Modbus Hardware
            final_registers = [None] * num_addresses
            if chosen_port == "COM_SIMULATED":
                import random
                raw_data = [random.randint(16000, 17500) for _ in range(num_addresses)]
                final_registers = process_modbus_registers(raw_data, swap_strategy)
            else:
                try:
                    if not client.connected: client.connect()
                    result = client.read_holding_registers(address=0, count=num_addresses, slave=slave_id)
                    if result and not result.isError():
                        final_registers = process_modbus_registers(result.registers, swap_strategy)
                except (ModbusException, Exception) as error:
                    print(f"[{current_timestamp.strftime('%H:%M:%S')}] ❌ Read Error: {error}")
                finally:
                    client.close()

            # 3. Append Record Straight to Local CSV File
            row_data = decode_registers_to_floats(final_registers)
            df_new_row = pd.DataFrame([row_data], index=[current_timestamp])
            df_new_row.index.name = 'Timestamp'
            
            file_exists = os.path.exists(output_csv_path)
            df_new_row.to_csv(output_csv_path, mode='a', header=not file_exists)
            
            print(df_new_row)
            print("-" * 75)
            
            time.sleep(interval_seconds)

    except KeyboardInterrupt:
        print("\nExecution terminated manually via terminal interrupt.")
    
    print(f"🏁 Sequence closed. Data safely preserved at: {output_csv_path}")

# --- Execution ---
if __name__ == "__main__":
    start_modbus_logger(
        file_name="telemetry_output", 
        num_addresses=8,            # Reads 8 addresses (Creates 8 integer columns and 4 float32 columns)
        interval_seconds=10.0, 
        swap_strategy="ABCD",       # Endian configurations: ABCD, BADC, CDAB, DCBA
        total_days=30.0
    )