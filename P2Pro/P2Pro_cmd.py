import enum
import struct
import time
import logging
import threading

import usb.util
import usb.core

log = logging.getLogger(__name__)


class PseudoColorTypes(enum.IntEnum):
    PSEUDO_WHITE_HOT = 1; PSEUDO_RESERVED = 2; PSEUDO_IRON_RED = 3; PSEUDO_RAINBOW_1 = 4;
    PSEUDO_RAINBOW_2 = 5; PSEUDO_RAINBOW_3 = 6; PSEUDO_RED_HOT = 7; PSEUDO_HOT_RED = 8;
    PSEUDO_RAINBOW_4 = 9; PSEUDO_RAINBOW_5 = 10; PSEUDO_BLACK_HOT = 11

class PropTpdParams(enum.IntEnum):
    TPD_PROP_DISTANCE = 0; TPD_PROP_TU = 1; TPD_PROP_TA = 2; TPD_PROP_EMS = 3;
    TPD_PROP_TAU = 4; TPD_PROP_GAIN_SEL = 5

class ShutterVTempParams(enum.IntEnum):
    SHUTTER_MANUAL_CORRECTION = 0x0100; SHUTTER_AUTO_ON = 0x01; SHUTTER_AUTO_OFF = 0x00

class DeviceInfoType(enum.IntEnum):
    DEV_INFO_CHIP_ID = 0; DEV_INFO_FW_COMPILE_DATE = 1; DEV_INFO_DEV_QUALIFICATION = 2;
    DEV_INFO_IR_INFO = 3; DEV_INFO_PROJECT_INFO = 4; DEV_INFO_FW_BUILD_VERSION_INFO = 5;
    DEV_INFO_GET_PN = 6; DEV_INFO_GET_SN = 7; DEV_INFO_GET_SENSOR_ID = 8
DeviceInfoType_len = [8, 8, 8, 26, 4, 50, 48, 16, 4]

class CmdDir(enum.IntFlag):
    GET = 0x0000; SET = 0x4000

class CmdCode(enum.IntEnum):
    sys_reset_to_rom = 0x0805; spi_transfer = 0x8201; get_device_info = 0x8405;
    pseudo_color = 0x8409; shutter_vtemp = 0x840c; prop_tpd_params = 0x8514;
    cur_vtemp = 0x8b0d; preview_start = 0xc10f; preview_stop = 0x020f;
    y16_preview_start = 0x010a; y16_preview_stop = 0x020a


class P2Pro:
    _dev: usb.core.Device

    def __init__(self):
        self._dev = usb.core.find(idVendor=0x0BDA, idProduct=0x5830)
        if (self._dev == None):
            raise FileNotFoundError("Infiray P2 Pro thermal module not found, please connect and try again!")
        # --- KORREKTUR: Re-entrant Lock für sicherere Thread-Sperrung ---
        self.lock = threading.RLock()
        pass

    def _block_until_camera_ready(self, timeout: int = 5) -> bool:
        start = time.time()
        while True:
            if self._check_camera_ready(): return True
            time.sleep(0.001)
            if time.time() > start + timeout: return False

    def _check_camera_ready(self) -> bool:
        ret = self._dev.ctrl_transfer(0xC1, 0x44, 0x78, 0x200, 1)
        if (ret[0] & 1 == 0 and ret[0] & 2 == 0): return True
        if (ret[0] & 0xFC != 0): raise UserWarning(f"vdcmd status error {ret[0]:#X}")
        return False

    def _long_cmd_write(self, cmd: int, p1: int, p2: int, p3: int = 0, p4: int = 0):
        data1 = struct.pack("<H", cmd); data1 += struct.pack(">HI", p1, p2)
        data2 = struct.pack(">II", p3, p4)
        self._dev.ctrl_transfer(0x41, 0x45, 0x78, 0x9d00, data1)
        self._dev.ctrl_transfer(0x41, 0x45, 0x78, 0x1d08, data2)
        self._block_until_camera_ready()

    def _long_cmd_read(self, cmd: int, p1: int, p2: int = 0, p3: int = 0, dataLen: int = 2):
        data1 = struct.pack("<H", cmd); data1 += struct.pack(">HI", p1, p2)
        data2 = struct.pack(">II", p3, dataLen)
        self._dev.ctrl_transfer(0x41, 0x45, 0x78, 0x9d00, data1)
        self._dev.ctrl_transfer(0x41, 0x45, 0x78, 0x1d08, data2)
        self._block_until_camera_ready()
        return bytes(self._dev.ctrl_transfer(0xC1, 0x44, 0x78, 0x1d10, dataLen))

    def _standard_cmd_write(self, cmd: int, cmd_param: int = 0, data: bytes = b'\x00', dataLen: int = -1):
        if dataLen == -1: dataLen = len(data)
        cmd_param = struct.unpack('<I', struct.pack('>I', cmd_param))[0]
        if (dataLen == 0 or data == b'\x00'):
            d = struct.pack("<H", cmd); d += struct.pack(">I2x", cmd_param)
            self._dev.ctrl_transfer(0x41, 0x45, 0x78, 0x1d00, d)
            self._block_until_camera_ready()
            return
        outer_chunk_size = 0x100
        for i in range(0, dataLen, outer_chunk_size):
            outer_chunk = data[i:i+outer_chunk_size]
            initial_data = struct.pack("<H", cmd); initial_data += struct.pack(">IH", cmd_param + i, len(outer_chunk))
            self._dev.ctrl_transfer(0x41, 0x45, 0x78, 0x9d00, initial_data)
            self._block_until_camera_ready()
            inner_chunk_size = 0x40
            for j in range(0, len(outer_chunk), inner_chunk_size):
                inner_chunk = outer_chunk[j:j+inner_chunk_size]
                to_send = len(outer_chunk) - j
                if (to_send <= 8):
                    self._dev.ctrl_transfer(0x41, 0x45, 0x78, 0x1d08 + j, inner_chunk)
                    self._block_until_camera_ready()
                elif (to_send <= 64):
                    self._dev.ctrl_transfer(0x41, 0x45, 0x78, 0x9d08 + j, inner_chunk[:-8])
                    self._dev.ctrl_transfer(0x41, 0x45, 0x78, 0x1d08 + j + to_send - 8, inner_chunk[-8:])
                    self._block_until_camera_ready()
                else: self._dev.ctrl_transfer(0x41, 0x45, 0x78, 0x9d08 + j, inner_chunk)
    
    def _standard_cmd_read(self, cmd: int, cmd_param: int = 0, dataLen: int = 0) -> bytes:
        if dataLen == 0: return b''
        cmd_param = struct.unpack('<I', struct.pack('>I', cmd_param))[0]
        result = b''; outer_chunk_size = 0x100
        for i in range(0, dataLen, outer_chunk_size):
            to_read = min(dataLen - i, outer_chunk_size)
            initial_data = struct.pack("<H", cmd); initial_data += struct.pack(">IH", cmd_param + i, to_read)
            self._dev.ctrl_transfer(0x41, 0x45, 0x78, 0x1d00, initial_data)
            self._block_until_camera_ready()
            res = self._dev.ctrl_transfer(0xC1, 0x44, 0x78, 0x1d08, to_read)
            result += bytes(res)
        return result

    # --- ÖFFENTLICHE METHODEN MIT LOCK UND PACING GESCHÜTZT ---
    def _execute_command(self, func, *args, **kwargs):
        with self.lock:
            result = func(*args, **kwargs)
            time.sleep(0.05)  # Pause zur Stabilisierung
            return result

    def pseudo_color_set(self, preview_path: int, color_type: PseudoColorTypes):
        return self._execute_command(self._standard_cmd_write, (CmdCode.pseudo_color | CmdDir.SET), preview_path, struct.pack("<B", color_type))

    def set_prop_tpd_params(self, tpd_param: PropTpdParams, value: int):
        return self._execute_command(self._long_cmd_write, CmdCode.prop_tpd_params | CmdDir.SET, tpd_param, value)

    def get_prop_tpd_params(self, tpd_param: PropTpdParams) -> int:
        res = self._execute_command(self._long_cmd_read, CmdCode.prop_tpd_params, tpd_param)
        return struct.unpack(">H", res)[0]

    def shutter_vtemp_set(self, shutter_vtemp: ShutterVTempParams):
        log.info(f"Setting shutter mode to {shutter_vtemp.name}...")
        return self._execute_command(self._long_cmd_write, CmdCode.shutter_vtemp | CmdDir.SET, shutter_vtemp, 0x00)

    def trigger_shutter(self):
        self.shutter_vtemp_set(ShutterVTempParams.SHUTTER_MANUAL_CORRECTION)

    def set_emissivity(self, emissivity: float):
        val = int(emissivity * 127)
        log.info(f"Setting emissivity to {emissivity} ({val})...")
        self.set_prop_tpd_params(PropTpdParams.TPD_PROP_EMS, val)

    # ... andere öffentliche Methoden können hier hinzugefügt werden, falls nötig ...