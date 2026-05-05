import socket
server_socket=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
server_socket.bind(('0.0.0.0',50050))
server_socket.listen()
print("Server is listening on port 50050...")


connected, addr = server_socket.accept()
print("Connection from ", addr)