#!/usr/bin/env python3
"""Read-only Windows UART -> one authorized IPv4 TCP client on a trusted LAN.

No serial TX, no encryption, no cryptographic authentication. Use an isolated
trusted network and a firewall scoped to the Host PC. Close SDK Terminal first.
"""
import argparse
import ipaddress
import select
import socket
import threading


def permitted(peer_ip, client_ip, already_connected):
    return peer_ip == client_ip and not already_connected


def forward_once(device, client):
    data = device.read(max(1, min(device.in_waiting, 65536)))
    if data and client is not None:
        client.sendall(data)
    return len(data)


def serve(device, listener, client_ip, stopped):
    client = None
    try:
        while not stopped.is_set():
            watched = [listener] + ([client] if client else [])
            ready, _, _ = select.select(watched, [], [], .05)
            if listener in ready:
                incoming, peer = listener.accept()
                if not permitted(peer[0], client_ip, client is not None):
                    incoming.close()
                    print(f"Rejected connection from {peer[0]}", flush=True)
                else:
                    incoming.settimeout(5)
                    client = incoming
                    print(f"Host connected: {peer[0]}", flush=True)
            if client in ready:
                # The client may only receive bytes. Never forward client data to
                # UART (cannot send X, reset firmware, or otherwise modify board).
                try:
                    unexpected = client.recv(4096)
                    reason = "unexpected client TX" if unexpected else "disconnect"
                except OSError:
                    reason = "connection failure"
                client.close()
                client = None
                print(f"Host disconnected: {reason}", flush=True)
            try:
                forward_once(device, client)
            except (ConnectionError, TimeoutError):
                if client:
                    client.close()
                    client = None
                print("TCP send failed; run must be checked for missing UART data", flush=True)
    finally:
        if client:
            client.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", required=True, help="Board UART COM port, e.g. COM3; not JTAG")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--bind", default="127.0.0.1", help="Laptop's private LAN IPv4 address")
    p.add_argument("--client-ip", required=True, help="Only this Host PC IPv4 may connect")
    p.add_argument("--tcp-port", type=int, default=8765)
    args = p.parse_args()
    try:
        bind = ipaddress.IPv4Address(args.bind)
        allowed = ipaddress.IPv4Address(args.client_ip)
    except ValueError:
        p.error("Numeric IPv4 addresses required")
    if not (bind.is_private and allowed.is_private) or bind.is_unspecified or allowed.is_unspecified:
        p.error("Use specific trusted private/loopback addresses, not wildcard or public interfaces")
    if args.baud <= 0 or not 1 <= args.tcp_port <= 65535:
        p.error("Invalid baud or TCP port")
    import serial
    with serial.Serial(args.port, baudrate=args.baud, timeout=.05) as device, \
            socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((str(bind), args.tcp_port))
        listener.listen(2)
        print(f"Read-only bridge: {args.port} ({args.baud} 8N1) -> {bind}:{args.tcp_port}; "
              f"allowed Host={allowed}. Ctrl+C to stop.", flush=True)
        try:
            serve(device, listener, str(allowed), threading.Event())
        except KeyboardInterrupt:
            print("Bridge stopped")


if __name__ == "__main__":
    main()
