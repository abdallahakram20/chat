import socket
import threading
import os
import struct
import zlib
import json
 
# ─────────────────────────────────────────────
#  Config
# ─────────────────────────────────────────────
HOST     = '0.0.0.0'
PORT = int(os.environ.get('PORT', 8080))
 
SAVE_DIR = "server_received_files"
os.makedirs(SAVE_DIR, exist_ok=True)
 
MSG_TEXT = 'TEXT'
MSG_FILE = 'FILE'
MSG_INFO = 'INFO'
 
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
VIDEO_EXTS = {'.mp4', '.avi', '.mkv', '.mov', '.webm', '.flv'}
 
clients   = []          # list of active sockets
usernames = {}          # socket -> username
lock      = threading.Lock()
 
 
# ─────────────────────────────────────────────
#  Packet helpers
# ─────────────────────────────────────────────
def send_packet(conn, msg_type, payload_bytes, meta=None):
    header       = {'type': msg_type, 'length': len(payload_bytes), 'meta': meta or {}}
    header_bytes = json.dumps(header).encode('utf-8')
    conn.sendall(struct.pack('>I', len(header_bytes)))
    conn.sendall(header_bytes)
    conn.sendall(payload_bytes)
 
 
def recv_exact(conn, n):
    data = b''
    while len(data) < n:
        chunk = conn.recv(n - len(data))
        if not chunk:
            raise ConnectionError("Connection closed")
        data += chunk
    return data
 
 
def recv_packet(conn):
    header_len = struct.unpack('>I', recv_exact(conn, 4))[0]
    header     = json.loads(recv_exact(conn, header_len).decode('utf-8'))
    payload    = recv_exact(conn, header['length'])
    return header['type'], payload, header.get('meta', {})
 
 
# ─────────────────────────────────────────────
#  Compression helpers
# ─────────────────────────────────────────────
def compress_data(data: bytes) -> bytes:
    return zlib.compress(data, level=6)
 
 
def decompress_data(data: bytes) -> bytes:
    return zlib.decompress(data)
 
 
def should_compress(ext: str) -> bool:
    return ext not in VIDEO_EXTS   # videos are already compressed
 
 
# ─────────────────────────────────────────────
#  Broadcast / remove client
# ─────────────────────────────────────────────
def broadcast(msg_type, payload_bytes, meta=None, exclude_conn=None):
    with lock:
        targets = [c for c in clients if c != exclude_conn]
    for client in targets:
        try:
            send_packet(client, msg_type, payload_bytes, meta)
        except Exception:
            remove_client(client)
 
 
def remove_client(conn):
    with lock:
        if conn not in clients:
            return
        username = usernames.pop(conn, 'Unknown')
        clients.remove(conn)
    try:
        conn.close()
    except Exception:
        pass
    broadcast(MSG_INFO, f"[-] {username} left the room.".encode('utf-8'))
    print(f"[DISCONNECTED] {username}")
 
 
# ─────────────────────────────────────────────
#  Per-client handler  (runs in its own thread)
# ─────────────────────────────────────────────
def handle_client(conn, addr):
    print(f"[NEW] {addr} connected")
    username = f"Guest_{addr[1]}"
 
    try:
        # First packet = username registration
        msg_type, payload, meta = recv_packet(conn)
        username = payload.decode('utf-8').strip() or username
 
        with lock:
            usernames[conn] = username
            clients.append(conn)
 
        print(f"[JOIN] {username}")
        broadcast(MSG_INFO, f"[+] {username} joined!".encode('utf-8'), exclude_conn=conn)
 
        # ── Main receive loop ──────────────────────────────────
        while True:
            msg_type, payload, meta = recv_packet(conn)
 
            # Text message → relay to everyone else
            if msg_type == MSG_TEXT:
                text = payload.decode('utf-8')
                full = f"{username}: {text}"
                print(f"[MSG] {full}")
                broadcast(MSG_TEXT, full.encode('utf-8'), exclude_conn=conn)
 
            # File (image / video / any) → save + relay compressed payload
            elif msg_type == MSG_FILE:
                filename   = meta.get('filename', 'unknown')
                ext        = meta.get('ext', '')
                compressed = meta.get('compressed', False)
                file_type  = meta.get('file_type', 'file')
                orig_size  = meta.get('original_size', 0)
 
                # Decompress locally just for saving
                file_data  = decompress_data(payload) if compressed else payload
                comp_ratio = (
                    round((1 - len(payload) / orig_size) * 100, 1)
                    if compressed and orig_size else 0
                )
 
                # Save a copy on the server
                save_path = os.path.join(SAVE_DIR, f"{username}_{filename}")
                with open(save_path, 'wb') as f:
                    f.write(file_data)
 
                size_kb = len(file_data) // 1024
                print(
                    f"[FILE] {username} -> '{filename}' | "
                    f"{size_kb} KB | type: {file_type} | compression: {comp_ratio}%"
                )
 
                # Forward the still-compressed payload to all other clients
                fwd_meta           = dict(meta)
                fwd_meta['sender'] = username
                broadcast(MSG_FILE, payload, meta=fwd_meta, exclude_conn=conn)
 
    except Exception as e:
        print(f"[ERROR] {addr}: {e}")
    finally:
        remove_client(conn)
 
 
# ─────────────────────────────────────────────
#  Accept loop  (runs in its own thread)
# ─────────────────────────────────────────────
def accept_loop(server: socket.socket):
    while True:
        try:
            conn, addr = server.accept()
            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()
        except Exception:
            break
 
 
# ─────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen()
    print(f"[START] Server listening on {HOST}:{PORT}")
    print(f"[INFO]  Files will be saved to: {os.path.abspath(SAVE_DIR)}")
    print("[INFO]  Press Ctrl+C to stop.\n")
 
    threading.Thread(target=accept_loop, args=(server,), daemon=True).start()
 
    try:
        threading.Event().wait()   # block main thread forever
    except KeyboardInterrupt:
        print("\n[STOP] Shutting down...")
    finally:
        server.close()
 
 
if __name__ == '__main__':
    main()