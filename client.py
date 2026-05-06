import socket
import threading
import os
import struct
import zlib
import json
import io
import tkinter as tk
from tkinter import simpledialog, messagebox, filedialog
from tkinter.scrolledtext import ScrolledText
from PIL import Image, ImageTk

# ─────────────────────────────────────────────
#  Config  ← غيّر HOST لـ IP السيرفر
# ─────────────────────────────────────────────
HOST = 'trolley.proxy.rlwy.net'
PORT = 59839

SAVE_DIR = "client_received_files"
os.makedirs(SAVE_DIR, exist_ok=True)

MSG_TEXT = 'TEXT'
MSG_FILE = 'FILE'
MSG_INFO = 'INFO'

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
VIDEO_EXTS = {'.mp4', '.avi', '.mkv', '.mov', '.webm', '.flv'}


# ─────────────────────────────────────────────
#  Packet helpers  (نفس السيرفر بالظبط)
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
#  Compression helpers  (نفس السيرفر بالظبط)
# ─────────────────────────────────────────────
def compress_data(data: bytes) -> bytes:
    return zlib.compress(data, level=6)


def decompress_data(data: bytes) -> bytes:
    return zlib.decompress(data)


def should_compress(filepath: str) -> bool:
    ext = os.path.splitext(filepath)[1].lower()
    if ext in VIDEO_EXTS:
        return False
    if ext in IMAGE_EXTS:
        return True
    return os.path.getsize(filepath) > 10_240


# ─────────────────────────────────────────────
#  Image display helper
# ─────────────────────────────────────────────
def display_image_in_chat(chat_box, image_data: bytes, label: str):
    try:
        img   = Image.open(io.BytesIO(image_data))
        img.thumbnail((220, 220))
        photo = ImageTk.PhotoImage(img)

        chat_box.config(state=tk.NORMAL)
        chat_box.insert(tk.END, f"{label}\n")
        chat_box.image_create(tk.END, image=photo)
        chat_box.insert(tk.END, "\n")
        chat_box.config(state=tk.DISABLED)
        chat_box.yview(tk.END)

        if not hasattr(chat_box, '_images'):
            chat_box._images = []
        chat_box._images.append(photo)
    except Exception:
        chat_box.config(state=tk.NORMAL)
        chat_box.insert(tk.END, f"{label} [File saved]\n")
        chat_box.config(state=tk.DISABLED)
        chat_box.yview(tk.END)


# ─────────────────────────────────────────────
#  Chat Client
# ─────────────────────────────────────────────
class ChatClient:

    def __init__(self):
        self.client   = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.username = None

        # اسأل عن الـ username قبل ما تعمل GUI
        root_tmp = tk.Tk()
        root_tmp.withdraw()
        self.username = simpledialog.askstring(
            "Username", "Enter your name:", parent=root_tmp
        )
        root_tmp.destroy()

        if not self.username:
            print("No username entered. Exiting.")
            return

        # اتصل بالسيرفر وابعت الـ username كأول packet
        try:
            self.client.connect((HOST, PORT))
            send_packet(self.client, MSG_TEXT, self.username.encode('utf-8'))
        except Exception as e:
            messagebox.showerror("Connection Error", str(e))
            return

        # ابني الـ GUI وابدأ thread الاستقبال
        self.root = tk.Tk()
        self._build_gui()
        threading.Thread(target=self._receive_loop, daemon=True).start()
        self.root.mainloop()

    # ── GUI ───────────────────────────────────
    def _build_gui(self):
        self.root.title(f"Chat — {self.username}")
        self.root.configure(bg='#1e1e2e')
        self.root.geometry('520x580')
        self.root.resizable(True, True)

        tk.Label(
            self.root, text=self.username,
            bg='#313244', fg='#cdd6f4',
            font=('Segoe UI', 13, 'bold'), pady=8
        ).pack(fill=tk.X)

        self.chat_box = ScrolledText(
            self.root, state=tk.DISABLED,
            bg='#181825', fg='#cdd6f4',
            font=('Segoe UI', 10), relief=tk.FLAT,
            wrap=tk.WORD, padx=10, pady=10
        )
        self.chat_box.pack(fill=tk.BOTH, expand=True, padx=8, pady=(6, 4))
        self.chat_box.tag_config('info',   foreground='#a6e3a1')
        self.chat_box.tag_config('self',   foreground='#89b4fa')
        self.chat_box.tag_config('other',  foreground='#cdd6f4')
        self.chat_box.tag_config('system', foreground='#f38ba8')

        input_frame = tk.Frame(self.root, bg='#1e1e2e')
        input_frame.pack(fill=tk.X, padx=8, pady=(0, 8))

        self.entry = tk.Entry(
            input_frame,
            bg='#313244', fg='#cdd6f4', insertbackground='white',
            relief=tk.FLAT, font=('Segoe UI', 10)
        )
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6, padx=(0, 6))
        self.entry.bind('<Return>', lambda e: self.send_text())

        btn = dict(relief=tk.FLAT, font=('Segoe UI', 9, 'bold'), padx=10, pady=6)
        tk.Button(
            input_frame, text='Send', command=self.send_text,
            bg='#89b4fa', fg='#1e1e2e', **btn
        ).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(
            input_frame, text='File', command=self.send_file,
            bg='#a6e3a1', fg='#1e1e2e', **btn
        ).pack(side=tk.LEFT)

    # ── Send text ─────────────────────────────
    def send_text(self):
        msg = self.entry.get().strip()
        if not msg:
            return
        try:
            send_packet(self.client, MSG_TEXT, msg.encode('utf-8'))
            self._append_chat(f"You: {msg}", tag='self')
            self.entry.delete(0, tk.END)
        except Exception as e:
            self._append_chat(f"[Send Error: {e}]", tag='system')

    # ── Send file ─────────────────────────────
    def send_file(self):
        filepath = filedialog.askopenfilename(
            title='Select a file to send',
            filetypes=[
                ('All Files', '*.*'),
                ('Images',    '*.jpg *.jpeg *.png *.gif *.bmp *.webp'),
                ('Videos',    '*.mp4 *.avi *.mkv *.mov *.webm *.flv'),
                ('Documents', '*.pdf *.txt *.docx *.zip *.rar'),
            ]
        )
        if not filepath:
            return

        try:
            filename  = os.path.basename(filepath)
            ext       = os.path.splitext(filename)[1].lower()
            file_type = (
                'image' if ext in IMAGE_EXTS else
                'video' if ext in VIDEO_EXTS else
                'file'
            )

            with open(filepath, 'rb') as f:
                raw_data = f.read()

            orig_size   = len(raw_data)
            do_compress = should_compress(filepath)

            if do_compress:
                payload    = compress_data(raw_data)
                comp_ratio = round((1 - len(payload) / orig_size) * 100, 1)
                self._append_chat(
                    f"Sending '{filename}' | {orig_size//1024} KB → "
                    f"{len(payload)//1024} KB (Compressed {comp_ratio}%)",
                    tag='info'
                )
            else:
                payload = raw_data
                self._append_chat(
                    f"Sending '{filename}' | {round(orig_size/(1024*1024), 2)} MB (no compression)",
                    tag='info'
                )

            meta = {
                'filename'      : filename,
                'file_type'     : file_type,
                'compressed'    : do_compress,
                'original_size' : orig_size,
                'ext'           : ext
            }

            # بعت في thread منفصل عشان الـ GUI ميتجمدش
            def _send():
                try:
                    send_packet(self.client, MSG_FILE, payload, meta=meta)
                    if file_type == 'image':
                        self.root.after(0, lambda: display_image_in_chat(
                            self.chat_box, raw_data, f"You sent image '{filename}':"))
                    elif file_type == 'video':
                        self.root.after(0, lambda: self._append_chat(
                            f"You sent video: '{filename}'", tag='self'))
                    else:
                        self.root.after(0, lambda: self._append_chat(
                            f"You sent file: '{filename}'", tag='self'))
                except Exception as e:
                    self.root.after(0, lambda: self._append_chat(
                        f"[File Send Error: {e}]", tag='system'))

            threading.Thread(target=_send, daemon=True).start()

        except Exception as e:
            self._append_chat(f"[File Error: {e}]", tag='system')

    # ── Receive loop (background thread) ──────
    def _receive_loop(self):
        while True:
            try:
                msg_type, payload, meta = recv_packet(self.client)

                if msg_type == MSG_TEXT:
                    text = payload.decode('utf-8')
                    self.root.after(0, lambda t=text: self._append_chat(t, tag='other'))

                elif msg_type == MSG_INFO:
                    info = payload.decode('utf-8')
                    self.root.after(0, lambda i=info: self._append_chat(i, tag='info'))

                elif msg_type == MSG_FILE:
                    sender     = meta.get('sender', 'Someone')
                    filename   = meta.get('filename', 'file')
                    file_type  = meta.get('file_type', 'file')
                    compressed = meta.get('compressed', False)
                    file_data  = decompress_data(payload) if compressed else payload

                    save_path = os.path.join(SAVE_DIR, f"{sender}_{filename}")
                    with open(save_path, 'wb') as f:
                        f.write(file_data)

                    if file_type == 'image':
                        self.root.after(0, lambda d=file_data, s=sender, fn=filename:
                            display_image_in_chat(
                                self.chat_box, d, f"{s} sent image '{fn}':"))
                    elif file_type == 'video':
                        msg = f"{sender} sent video: '{filename}' — Saved to {save_path}"
                        self.root.after(0, lambda m=msg: self._append_chat(m, tag='other'))
                    else:
                        msg = f"{sender} sent file: '{filename}' — Saved to {save_path}"
                        self.root.after(0, lambda m=msg: self._append_chat(m, tag='other'))

            except Exception:
                self.root.after(0, lambda: self._append_chat(
                    "Connection to server lost.", tag='system'))
                break

    # ── Append to chat box ────────────────────
    def _append_chat(self, text: str, tag: str = 'other'):
        self.chat_box.config(state=tk.NORMAL)
        self.chat_box.insert(tk.END, text + '\n', tag)
        self.chat_box.config(state=tk.DISABLED)
        self.chat_box.yview(tk.END)


# ─────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────
if __name__ == '__main__':
    ChatClient()