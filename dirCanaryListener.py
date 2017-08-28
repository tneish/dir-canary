#!/usr/bin/python3
import sys
import select
import socket
import subprocess
from time import sleep

DEBUG = True
events_waiting = []
EOL1 = b'\n\n'
EOL2 = b'\n\r\n'

# these variables can be modified
class config:
    fileServerPort = 54893
    response = b'OK!'

class enum_eventtype:
    epoll = 0
    file_transfer = 1
    event_types = [epoll, file_transfer]

def addEvent(event_type, *event_data):
    global events_waiting
    if not event_type in enum_eventtype.event_types:
        print('Error: Invalid event type: ' + str(event_type) + '. Ignoring.')
        return 1
    events_waiting.append([event_type, event_data])
    return 0

def clearEvents():
    global events_waiting
    events_waiting = []
    return 0

def main():
    #if (len(sys.argv) < 2):
    #    usage()
    #    sys.exit(1)
    if DEBUG: print(str(sys.argv))

    serversocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    serversocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    serversocket.bind(('0.0.0.0', config.fileServerPort))
    serversocket.listen(1)
    serversocket.setblocking(0)
    print('Listening on port ' + str(config.fileServerPort) + '.')

    epoll = select.epoll()
    epoll.register(serversocket.fileno(), select.EPOLLIN)

    try:
        connections = {}; requests = {}; responses = {}
        pendingFileTransfer = False
        while True:
            ### fill queue with any waiting epoll events
            epoll_waiting = epoll.poll(0)  # get all events waiting (return immediately)
            for fileno, event in epoll_waiting:
                addEvent(enum_eventtype.epoll, fileno, event)

            ### process all queued events
            for queued_event in events_waiting:
                if DEBUG: print('Processing event: ' + str(queued_event) + '.')
                if queued_event[0] == enum_eventtype.epoll:
                    fileno = queued_event[1][0]
                    event = queued_event[1][1]
                    if fileno == serversocket.fileno():
                        connection, address = serversocket.accept()
                        if DEBUG: print('New connection from ' + str(address) + '.')
                        connection.setblocking(0)
                        epoll.register(connection.fileno(), select.EPOLLIN)
                        connections[connection.fileno()] = connection
                        requests[connection.fileno()] = b''
                        responses[connection.fileno()] = config.response
                    elif event & select.EPOLLIN:
                        requests[fileno] += connections[fileno].recv(1024)
                        if EOL1 in requests[fileno] or EOL2 in requests[fileno]:
                            epoll.modify(fileno, select.EPOLLOUT)
                            if DEBUG: print('Rx\'d request on socket ' + str(fileno) + ' (see below). Queueing response.' + '\n' + requests[fileno].decode()[:-2])
                    elif event & select.EPOLLOUT:
                        byteswritten = connections[fileno].send(responses[fileno])
                        responses[fileno] = responses[fileno][byteswritten:]
                        if len(responses[fileno]) == 0:
                            epoll.modify(fileno, 0)
                            print('Sent response on socket ' + str(fileno) + '. Closing socket.')
                            connections[fileno].shutdown(socket.SHUT_RDWR)
                            if pendingFileTransfer:
                                if DEBUG: print('File transfer already queued. Ignoring request.')
                            else:
                                print('Request from ' + str(connections[fileno].getpeername()) + '. Adding sftp cmd to event queue.')
                                addEvent(enum_eventtype.file_transfer, 0)
                                pendingFileTransfer = True
                    elif event & select.EPOLLHUP:
                        print('Hangup signal on socket: ' + str(fileno) + '. Closing this end too.')
                        epoll.unregister(fileno)
                        connections[fileno].close()
                        del connections[fileno]
                elif queued_event[0] == enum_eventtype.file_transfer:
                    print('Spawning sftp subprocess (blocking)...')
                    resobj = subprocess.run([ \
                            "sftp", "-b", "batch.txt", \
                            "-i", "/home/user/.ssh/id_rsa", \
                            "user@10.0.1.1"], stdout=subprocess.PIPE)
                    pendingFileTransfer = False
                    if DEBUG: print(str(resobj))

                else:
                    print('Received unknown event')

            # iterated through event queue. Now clear it
            clearEvents()
            sleep(0.05)  # in seconds

    finally:
        if DEBUG: print('Closing server socket ' + str(serversocket.fileno()) + '.')
        epoll.unregister(serversocket.fileno())
        epoll.close()
        serversocket.close()

#def usage():
#    print('Usage:\n' + sys.argv[0] + ' <directory1 to monitor> <directory2 to monitor> ...')

if __name__ == "__main__":
    sys.exit(main())

