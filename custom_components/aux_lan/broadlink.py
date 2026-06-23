"""BroadLink DNA LAN protocol — AES-128-CBC, UDP port 80."""
from __future__ import annotations

import asyncio
import logging
import socket
import struct
from dataclasses import dataclass, field
from enum import IntEnum

try:
    from Cryptodome.Cipher import AES
except ImportError:
    from Crypto.Cipher import AES  # type: ignore[no-redef]

_LOGGER = logging.getLogger(__name__)

UDP_PORT = 80
TIMEOUT = 3.0
HEADER_LEN = 0x38

MAGIC = bytes([0x5A, 0xA5, 0xAA, 0x55, 0x5A, 0xA5, 0xAA, 0x55])
DEFAULT_KEY = bytes([
    0x09, 0x76, 0x28, 0x34, 0x3F, 0xE9, 0x9E, 0x23,
    0x76, 0x5C, 0x15, 0x13, 0xAC, 0xCF, 0x8B, 0x02,
])
DEFAULT_IV = bytes([
    0x56, 0x2E, 0x17, 0x99, 0x6D, 0x09, 0x3D, 0x28,
    0xDD, 0xB3, 0xBA, 0x69, 0x5A, 0x2E, 0x6F, 0x58,
])

CMD_AUTH = 0x65
CMD_PACKET = 0x6A
RSP_AUTH = 0xE9
RSP_STATE = 0xEE

GET_STATE = bytes.fromhex("0C00BB0006800000020011012B7E0000")
GET_INFO = bytes.fromhex("0C00BB0006800000020021011B7E0000")


class BroadlinkError(Exception):
    pass


class BroadlinkAuthError(BroadlinkError):
    pass


class BroadlinkTimeoutError(BroadlinkError):
    pass


class AcMode(IntEnum):
    AUTO = 0
    COOLING = 1
    DRY = 2
    HEATING = 4
    FAN = 6


class AcFanSpeed(IntEnum):
    HIGH = 1
    MEDIUM = 2
    LOW = 3
    TURBO = 4
    AUTO = 5


@dataclass
class AcState:
    power: bool = False
    target_temp: float = 24.0
    mode: AcMode = AcMode.COOLING
    fan_speed: AcFanSpeed = AcFanSpeed.AUTO
    turbo: bool = False
    mute: bool = False
    sleep: bool = False
    health: bool = False
    display: bool = True
    clean: bool = False
    mildew: bool = False
    fixation_v: int = 0
    fixation_h: int = 7
    ambient_temp: float | None = None
    available: bool = False


def _checksum(data: bytes) -> int:
    val = 0xBEAF
    for b in data:
        val += b
    return val & 0xFFFF


def _internet_checksum(data: bytes) -> int:
    if len(data) % 2:
        data += b"\x00"
    total = 0
    for i in range(0, len(data), 2):
        word = (data[i] << 8) + data[i + 1]
        total += word
    total = (total >> 16) + (total & 0xFFFF)
    total += total >> 16
    return (~total) & 0xFFFF


def _pad16(data: bytes) -> bytes:
    rem = len(data) % 16
    if rem:
        data += b"\x00" * (16 - rem)
    return data


def _encrypt(key: bytes, plaintext: bytes) -> bytes:
    plaintext = _pad16(plaintext)
    cipher = AES.new(key, AES.MODE_CBC, DEFAULT_IV)
    return cipher.encrypt(plaintext)


def _decrypt(key: bytes, ciphertext: bytes) -> bytes:
    cipher = AES.new(key, AES.MODE_CBC, DEFAULT_IV)
    return cipher.decrypt(ciphertext)


def _build_packet(
    cmd: int,
    mac: bytes,
    device_id: bytes,
    key: bytes,
    payload: bytes,
    pkt_count: int = 0,
) -> bytes:
    inner_cs = _checksum(payload)
    encrypted = _encrypt(key, payload)

    header = bytearray(0x38)
    header[0:8] = MAGIC
    header[0x24] = 0x2A
    header[0x25] = 0x27
    header[0x26] = cmd
    struct.pack_into("<H", header, 0x28, pkt_count)
    header[0x2A:0x30] = mac
    header[0x30:0x34] = device_id
    struct.pack_into("<H", header, 0x34, inner_cs)

    packet = bytes(header) + encrypted
    outer_cs = _checksum(packet)
    packet = packet[:0x20] + struct.pack("<H", outer_cs) + packet[0x22:]
    return packet


class BroadlinkLanDevice:
    def __init__(self, ip: str, mac: str) -> None:
        self.ip = ip
        self.mac = bytes.fromhex(mac.replace(":", ""))
        self.device_key: bytes | None = None
        self.device_id: bytes = b"\x00" * 4
        self._pkt_count = 0

    async def auth(self) -> None:
        _LOGGER.debug("[%s] auth start", self.ip)
        payload = bytearray(0x50)
        payload[0x04:0x10] = b"\x31" * 12
        payload[0x1E] = 0x01
        payload[0x2D] = 0x01
        name = b"aux_lan"
        payload[0x30:0x30 + len(name)] = name

        packet = _build_packet(
            CMD_AUTH,
            self.mac,
            b"\x00" * 4,
            DEFAULT_KEY,
            bytes(payload),
            self._pkt_count,
        )
        self._pkt_count += 1

        try:
            response = await self._send_recv(packet)
        except BroadlinkTimeoutError as exc:
            raise BroadlinkAuthError(f"auth timeout {self.ip}") from exc

        decrypted = _decrypt(DEFAULT_KEY, response[0x38:])
        self.device_id = decrypted[0x00:0x04]
        self.device_key = decrypted[0x04:0x14]
        _LOGGER.debug("[%s] auth ok key=%s", self.ip, self.device_key.hex())

    def _decrypt_payload(self, response: bytes, ctx: str) -> bytes:
        """Decrypt a device response payload.

        A short response (header only, no encrypted body) is the module's way
        of saying it rejected our session — typically because it rebooted and
        forgot the device_key we authed with. Surface it as BroadlinkAuthError
        and drop the key so the coordinator re-auths instead of swallowing it
        as a generic UpdateFailed and getting stuck forever.
        """
        if len(response) <= HEADER_LEN:
            err = None
            if len(response) >= 0x24:
                err = struct.unpack("<h", response[0x22:0x24])[0]
            _LOGGER.warning(
                "[%s] %s: short response len=%d err_code=%s — stale session, forcing re-auth",
                self.ip, ctx, len(response), err,
            )
            self.device_key = None
            raise BroadlinkAuthError(f"stale session {self.ip} ({ctx}) err={err}")
        return _decrypt(self.device_key, response[HEADER_LEN:])

    async def get_state(self) -> AcState:
        if self.device_key is None:
            raise BroadlinkAuthError("not authenticated")

        packet = _build_packet(
            CMD_PACKET,
            self.mac,
            self.device_id,
            self.device_key,
            GET_STATE,
            self._pkt_count,
        )
        self._pkt_count += 1
        response = await self._send_recv(packet)
        payload = self._decrypt_payload(response, "get_state")
        _LOGGER.debug("[%s] get_state payload=%s", self.ip, payload[:24].hex())

        if len(payload) < 23:
            self.device_key = None
            raise BroadlinkAuthError(
                f"get_state truncated payload len={len(payload)} {self.ip}"
            )

        state = AcState()
        state.target_temp = 8 + (payload[12] >> 3)
        state.power = bool((payload[20] >> 5) & 0x01)
        mode_val = (payload[17] >> 5) & 0x0F
        try:
            state.mode = AcMode(mode_val)
        except ValueError:
            state.mode = AcMode.COOLING
        fan_val = (payload[15] >> 5) & 0x07
        try:
            state.fan_speed = AcFanSpeed(fan_val)
        except ValueError:
            state.fan_speed = AcFanSpeed.AUTO
        state.mute = bool((payload[16] >> 7) & 0x01)
        state.turbo = bool((payload[16] >> 6) & 0x01)
        state.sleep = bool((payload[17] >> 2) & 0x01)
        state.health = bool((payload[20] >> 1) & 0x01)
        state.clean = bool((payload[20] >> 2) & 0x01)
        if len(payload) > 22:
            state.display = bool((payload[22] >> 4) & 0x01)
            state.mildew = bool((payload[22] >> 3) & 0x01)
        state.fixation_v = payload[10] & 0x07
        state.fixation_h = (payload[11] >> 5) & 0x07
        state.available = True
        return state

    async def get_info(self) -> float | None:
        if self.device_key is None:
            raise BroadlinkAuthError("not authenticated")

        packet = _build_packet(
            CMD_PACKET,
            self.mac,
            self.device_id,
            self.device_key,
            GET_INFO,
            self._pkt_count,
        )
        self._pkt_count += 1
        try:
            response = await self._send_recv(packet)
        except BroadlinkTimeoutError:
            _LOGGER.debug("[%s] get_info timeout", self.ip)
            return None

        payload = self._decrypt_payload(response, "get_info")
        _LOGGER.debug("[%s] get_info payload=%s", self.ip, payload[:40].hex())

        if len(payload) < 34:
            return None
        amb_05 = payload[33] / 10.0
        amb_base = payload[17] & 0x1F
        if payload[17] > 63:
            amb_base += 32
        return amb_05 + amb_base

    async def set_state(
        self,
        power: bool,
        temp: float,
        mode: AcMode,
        fan_speed: AcFanSpeed,
        turbo: bool = False,
        mute: bool = False,
        sleep: bool = False,
        health: bool = False,
        display: bool = True,
        clean: bool = False,
        mildew: bool = False,
        fixation_v: int = 0,
        fixation_h: int = 7,
        caller: str = "",
    ) -> None:
        if self.device_key is None:
            raise BroadlinkAuthError("not authenticated")

        half_degree = 1 if (temp - int(temp)) >= 0.5 else 0

        cmd = bytearray(23)
        cmd[0] = 0xBB
        cmd[2] = 0x06
        cmd[3] = 0x80
        cmd[6] = 0x0F
        cmd[8] = 0x01
        cmd[9] = 0x01
        cmd[10] = ((int(temp) - 8) << 3) | (fixation_v & 0x07)
        cmd[11] = (fixation_h & 0x07) << 5
        cmd[12] = 0x0F | (half_degree << 7)
        cmd[13] = (int(fan_speed) & 0x07) << 5
        cmd[14] = (int(turbo) << 6) | (int(mute) << 7)
        cmd[15] = (int(mode) & 0x0F) << 5 | (int(sleep) << 2)
        cmd[18] = (int(power) << 5) | (int(health) << 1) | (int(clean) << 2)
        cmd[20] = (int(display) << 4) | (int(mildew) << 3)

        req = bytearray(32)
        req[0] = 25
        req[2:25] = cmd
        ic = _internet_checksum(bytes(cmd))
        req[25] = (ic >> 8) & 0xFF
        req[26] = ic & 0xFF

        _LOGGER.info(
            "[%s] set_state caller=%s power=%s temp=%s mode=%s fan=%s turbo=%s mute=%s sleep=%s "
            "health=%s display=%s clean=%s mildew=%s fix_v=%s fix_h=%s",
            self.ip, caller, power, temp, mode, fan_speed, turbo, mute, sleep,
            health, display, clean, mildew, fixation_v, fixation_h,
        )

        packet = _build_packet(
            CMD_PACKET,
            self.mac,
            self.device_id,
            self.device_key,
            bytes(req),
            self._pkt_count,
        )
        self._pkt_count += 1
        await self._send_recv(packet)
        _LOGGER.debug("[%s] set_state ok power=%s temp=%s mode=%s", self.ip, power, temp, mode)

    async def _send_recv(self, packet: bytes) -> bytes:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._send_recv_sync, packet)

    def _send_recv_sync(self, packet: bytes) -> bytes:
        for attempt in range(2):
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(TIMEOUT)
            try:
                sock.sendto(packet, (self.ip, UDP_PORT))
                data, _ = sock.recvfrom(2048)
                return data
            except socket.timeout:
                if attempt == 0:
                    _LOGGER.debug("[%s] timeout attempt 1, retrying", self.ip)
                    continue
                raise BroadlinkTimeoutError(f"timeout {self.ip}:{UDP_PORT}")
            finally:
                sock.close()
        raise BroadlinkTimeoutError(f"timeout {self.ip}:{UDP_PORT}")
