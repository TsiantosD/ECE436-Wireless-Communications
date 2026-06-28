#!/usr/bin/env python3
"""Sweep Wi-Fi channels on a monitor interface and ask the local AP to follow.

Intended node: unfair STA/node.  The script listens for beacon frames from a
victim/target AP while hopping a monitor interface across channels.  When it
finds a matching beacon, it sends a UDP control message to the unfair AP asking
it to switch to the channel where the beacon was seen.

Prerequisites on the unfair node:
  apt install python3-scapy -y
  iw dev wlan0 interface add mon1 type monitor
  ifconfig mon1 up

Example:
  ./unfair_beacon_channel_hunter.py \
      --ap-control-ip 192.168.3.1 \
      --target-ssid tsiantos \
      --ignore-bssid 04:54:53:00:aa:bb
"""

import argparse
import json
import socket
import subprocess
import sys
import time
from typing import Iterable, Optional

try:
    from scapy.all import Dot11, Dot11Beacon, Dot11Elt, sniff  # type: ignore
    SCAPY_IMPORT_ERROR = None
except ImportError as exc:  # pragma: no cover - depends on node package state
    Dot11 = Dot11Beacon = Dot11Elt = sniff = None  # type: ignore
    SCAPY_IMPORT_ERROR = exc


DEFAULT_CHANNELS = list(range(1, 12))


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def parse_channels(value):
    channels = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if "-" in item:
            start_s, end_s = item.split("-", 1)
            start, end = int(start_s), int(end_s)
            if start > end:
                raise argparse.ArgumentTypeError(f"bad channel range: {item}")
            channels.extend(range(start, end + 1))
        else:
            channels.append(int(item))
    if not channels:
        raise argparse.ArgumentTypeError("empty channel list")
    for ch in channels:
        if ch < 1 or ch > 14:
            raise argparse.ArgumentTypeError(f"unsupported 2.4GHz channel: {ch}")
    # Keep order while removing duplicates.
    return list(dict.fromkeys(channels))


def set_channel(iface: str, channel: int) -> bool:
    proc = subprocess.run(
        ["iw", "dev", iface, "set", "channel", str(channel)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    if proc.returncode != 0:
        print(f"[{now()}] WARN: failed to set {iface} to channel {channel}: {proc.stderr.strip()}", file=sys.stderr)
        return False
    return True


def dot11elt_iter(pkt) -> Iterable:
    elt = pkt.getlayer(Dot11Elt)
    while elt is not None:
        yield elt
        elt = elt.payload.getlayer(Dot11Elt)


def beacon_ssid(pkt) -> str:
    elt = pkt.getlayer(Dot11Elt, ID=0)
    if elt is None:
        return ""
    raw = bytes(elt.info or b"")
    return raw.decode("utf-8", "ignore")


def beacon_channel(pkt, fallback: int) -> int:
    """Return DS Parameter Set channel from beacon, else fallback scan channel."""
    for elt in dot11elt_iter(pkt):
        if getattr(elt, "ID", None) == 3 and getattr(elt, "info", None):
            data = bytes(elt.info)
            if data:
                ch = int(data[0])
                if 1 <= ch <= 14:
                    return ch
        # HT Operation element: primary channel is byte 0 of ID 61.
        if getattr(elt, "ID", None) == 61 and getattr(elt, "info", None):
            data = bytes(elt.info)
            if data:
                ch = int(data[0])
                if 1 <= ch <= 14:
                    return ch
    return fallback


class BeaconHit:
    def __init__(self, channel, bssid, ssid, rssi):
        self.channel = channel
        self.bssid = bssid
        self.ssid = ssid
        self.rssi = rssi


class BeaconHunter:
    def __init__(self, args: argparse.Namespace) -> None:
        assert Dot11 is not None and Dot11Beacon is not None and Dot11Elt is not None and sniff is not None
        self.args = args
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.last_notified_channel: Optional[int] = None
        self.last_notification_time = 0.0

        self.target_bssid = args.target_bssid.lower() if args.target_bssid else None
        self.ignore_bssids = {b.lower() for b in args.ignore_bssid}
        self.target_ssid = args.target_ssid
        self.ignore_ssids = set(args.ignore_ssid)

    def packet_matches(self, pkt, scan_channel: int) -> Optional[BeaconHit]:
        if not pkt.haslayer(Dot11Beacon):
            return None
        dot11 = pkt.getlayer(Dot11)
        bssid = (getattr(dot11, "addr2", None) or "").lower()
        if not bssid:
            return None
        ssid = beacon_ssid(pkt)

        if bssid in self.ignore_bssids:
            return None
        if ssid in self.ignore_ssids:
            return None
        if self.target_bssid and bssid != self.target_bssid:
            return None
        if self.target_ssid is not None and ssid != self.target_ssid:
            return None

        rssi = getattr(pkt, "dBm_AntSignal", None)
        return BeaconHit(channel=beacon_channel(pkt, scan_channel), bssid=bssid, ssid=ssid, rssi=rssi)

    def notify_ap(self, hit: BeaconHit) -> None:
        now_ts = time.time()
        if (
            self.last_notified_channel == hit.channel
            and now_ts - self.last_notification_time < self.args.min_notify_interval
        ):
            return

        payload = {
            "type": "channel_switch",
            "channel": hit.channel,
            "bssid": hit.bssid,
            "ssid": hit.ssid,
            "seen_at": now(),
            "source": "unfair_beacon_channel_hunter.py",
        }
        if self.args.token:
            payload["token"] = self.args.token
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")

        if self.args.dry_run:
            print(f"[{now()}] DRY-RUN notify {self.args.ap_control_ip}:{self.args.ap_control_port}: {data.decode()}")
        else:
            self.sock.sendto(data, (self.args.ap_control_ip, self.args.ap_control_port))
            print(
                f"[{now()}] notified AP {self.args.ap_control_ip}:{self.args.ap_control_port} "
                f"to switch to channel {hit.channel} after beacon ssid={hit.ssid!r} bssid={hit.bssid}"
            )
        self.last_notified_channel = hit.channel
        self.last_notification_time = now_ts

    def run_once_on_channel(self, channel: int) -> None:
        if not set_channel(self.args.monitor_iface, channel):
            return
        print(f"[{now()}] scanning channel {channel} for {self.args.dwell_seconds:.3f}s")

        notified = False

        def handler(pkt) -> None:
            nonlocal notified
            hit = self.packet_matches(pkt, channel)
            if hit is None:
                return
            print(
                f"[{now()}] beacon: ssid={hit.ssid!r} bssid={hit.bssid} "
                f"beacon_channel={hit.channel} scan_channel={channel} rssi={hit.rssi}"
            )
            self.notify_ap(hit)
            notified = True

        sniff(
            iface=self.args.monitor_iface,
            prn=handler,
            timeout=self.args.dwell_seconds,
            store=False,
            stop_filter=(lambda _pkt: notified and self.args.stop_after_match),
        )

    def run(self) -> None:
        print(f"[{now()}] starting beacon hunter on {self.args.monitor_iface}")
        print(f"[{now()}] channels={self.args.channels} dwell={self.args.dwell_seconds}s")
        print(f"[{now()}] target_ssid={self.target_ssid!r} target_bssid={self.target_bssid!r}")
        try:
            while True:
                for channel in self.args.channels:
                    self.run_once_on_channel(channel)
                    if self.args.once and self.last_notified_channel is not None:
                        return
        except KeyboardInterrupt:
            print(f"\n[{now()}] stopping beacon hunter")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Sweep channels for beacon frames and notify AP via UDP to follow.")
    p.add_argument("--monitor-iface", default="mon1", help="monitor-mode interface used for Scapy sniffing")
    p.add_argument("--ap-control-ip", required=True, help="Wi-Fi IP of the unfair AP running ap_channel_switch_server.py")
    p.add_argument("--ap-control-port", type=int, default=4444, help="UDP port of AP channel-switch server")
    p.add_argument("--channels", type=parse_channels, default=DEFAULT_CHANNELS, help="channels to sweep, e.g. 1-11 or 1,6,11")
    p.add_argument("--dwell-seconds", type=float, default=0.35, help="seconds to remain on each channel; use >0.1s beacon interval")
    p.add_argument("--min-notify-interval", type=float, default=2.0, help="minimum seconds between repeated notifications for same channel")
    p.add_argument("--target-ssid", help="only react to this SSID; omit to react to any non-ignored beacon")
    p.add_argument("--target-bssid", help="only react to this BSSID")
    p.add_argument("--ignore-ssid", action="append", default=[], help="SSID to ignore; may be repeated")
    p.add_argument("--ignore-bssid", action="append", default=[], help="BSSID to ignore; may be repeated")
    p.add_argument("--token", help="optional shared token included in UDP JSON payload")
    p.add_argument("--once", action="store_true", help="exit after first AP notification")
    p.add_argument("--stop-after-match", action="store_true", help="stop current dwell as soon as a matching beacon is seen")
    p.add_argument("--dry-run", action="store_true", help="print UDP messages instead of sending them")
    return p


def main() -> int:
    args = build_arg_parser().parse_args()
    if args.dwell_seconds <= 0:
        print("ERROR: --dwell-seconds must be positive", file=sys.stderr)
        return 2
    if SCAPY_IMPORT_ERROR is not None:
        print("ERROR: scapy is not installed. Run: apt install python3-scapy -y", file=sys.stderr)
        return 2
    BeaconHunter(args).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
