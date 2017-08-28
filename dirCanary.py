#!/usr/local/bin/python
import os
import sys
import select
import socket

DEBUG = True

# these variables can be modified
class config:
    timeAfterLastWrite = 60*1000  # milliseconds
    fileServerIPv4Address = '10.0.1.254'
    fileServerPort = 54893
    pingRetryInterval = 60000 # milliseconds

fdsWatched = []
fileTimerId = 65500 # at end of range not to collide with file descriptors for directories
pingTimerId = 65400 # needs to be at least 3 less than fileTimerId
timerStarted = {}

def deleteTimer(kq = None, fd = 0):
    global timerStarted
    if (fd == 0 or kq == None):
        return 1
    ev = [select.kevent(fd,
                        filter=select.KQ_FILTER_TIMER, 
                        flags=select.KQ_EV_DELETE,
                        )]
    if DEBUG: print('Deleting timer with event: ' + str(ev))
    kq.control(ev, 0, 0)
    timerStarted[fd] = False

def startOrRestartTimer(kq = None, fd = 0, timeout = 0, udata=None):
    global timerStarted
    if (kq == None or fd == 0 or timeout == 0):
        return 1
    if udata == None: udata = fd
    if fd not in timerStarted.keys():
        timerStarted[fd] = False
    if timerStarted[fd]:
        deleteTimer(kq, fd)
    ev = [select.kevent(fd,
                        filter=select.KQ_FILTER_TIMER,
                        flags=select.KQ_EV_ADD,
                        data = timeout,
                        udata = udata
                        )]
    if DEBUG: print('Starting timer with event: ' + str(ev))
    kq.control(ev, 0, 0)
    timerStarted[fd] = True

def startOrRestartFwatch(kq = None, fd = 0, udata = None):
    if (kq == None or fd == 0):
        return 1
    if udata == None: udata = fd
    ev = [select.kevent(fd,
                        filter=select.KQ_FILTER_VNODE, 
                        flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE | select.KQ_EV_ONESHOT,
                        fflags=select.KQ_NOTE_WRITE,
                        udata=udata
                        )]
    if DEBUG: print('Adding fwatch with event: ' + str(ev))
    kq.control(ev, 0, 0)

def pingFileServer():
    msgPayload = b't\n\n'
    ret = -1
    # ipv4, tcp
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(5) # in seconds
        sock.connect((config.fileServerIPv4Address, config.fileServerPort))
        if DEBUG: print('Connected to remote host ' + str(config.fileServerIPv4Address) + \
                ', port ' + str(config.fileServerPort) + ' OK!')
        totalsent = 0
        while totalsent < len(msgPayload):
            sent = sock.send(msgPayload[totalsent:])
            if (sent == 0):
                raise RuntimeError('Broken socket!')
            totalsent = totalsent + sent
        if DEBUG: print('Sent ' + str(totalsent) + ' bytes on socket.')
        bytes_recd = 0
        # if anything is returned on the socket we assume our ping was received OK, and move on
        chunk = sock.recv(1)   # force return as fast as possible if data in recv buffer (max 1B)
        if chunk == '':
            raise RuntimeError('Broken socket!')
        bytes_recd = bytes_recd + len(chunk)
        if DEBUG: print('Received ' + str(bytes_recd) + ' bytes back on socket!')
        sock.shutdown(socket.SHUT_RDWR)
        ret = 0
    except OSError as e:
        print('OSError! : ' + str(e))
        ret = 1
    except RuntimeError:
        print('Broken socket!')
        ret = 1
    except ConnectionRefusedError:
        print('Connection refused by remote host.')
        ret = 1
    finally:
        sock.close()
    return ret

def main():
    global fdsWatched
    if (len(sys.argv) < 2):
        usage()
        sys.exit(1)
    if DEBUG: print(str(sys.argv))
    kq = select.kqueue()
    try:
        for path in sys.argv[1:]:
            fd = os.open(path, os.O_DIRECTORY)
            startOrRestartFwatch(kq, fd)
            fdsWatched.append(fd)
        if DEBUG: print('fdsWatched: ' + str(fdsWatched))

        while True:
            wevents = kq.control([], 1, None) # get 1 event from queue (blocking)
            if DEBUG: print('Received an event:')
            for event in wevents: # should only be one; wevents is a list
                if DEBUG: print(str(event))
                if event.filter == select.KQ_FILTER_VNODE:
                    if DEBUG: print('Starting/Refreshing timer')
                    startOrRestartTimer(kq, fileTimerId, config.timeAfterLastWrite)
                    # need to re-add kevent because vnode event is oneshot
                    if DEBUG: print('Starting Fwatch again')
                    # file descriptor of kevent that fired is stored in udata (udata is passed transparently through kernel)
                    startOrRestartFwatch(kq, int(event.udata))
    
                elif event.filter == select.KQ_FILTER_TIMER and event.ident == fileTimerId:
                    # no writes to directories for <timer> seconds after first write
                    if DEBUG: print('Timer fired. Deleting timer')
                    deleteTimer(kq, fileTimerId)
                    print('Pinging file-server')
                    ret = pingFileServer()
                    if (ret != 0): # fail
                        print('Could not ping file server, will retry.')
                        numRetriesLeft = 3
                        startOrRestartTimer(kq, pingTimerId, config.pingRetryInterval, udata=numRetriesLeft)
                    else:
                        print('Success!')

                elif event.filter == select.KQ_FILTER_TIMER and event.ident == pingTimerId:
                    numRetriesLeft = int(event.udata)
                    deleteTimer(kq, pingTimerId)
                    # retry ping
                    print('Retrying file-server ping, numRetriesLeft = ' + str(numRetriesLeft))
                    ret = pingFileServer()
                    if (ret != 0): # fail
                        if numRetriesLeft == 1:
                            print('Could not ping file server. Sleeping')
                            continue
                        else:
                            print('Could not ping file server, will retry.')
                            numRetriesLeft -= 1
                            startOrRestartTimer(kq, pingTimerId, config.pingRetryInterval, udata=int(numRetriesLeft))
                    else:
                        print('Success!')

                elif event.flags == select.KQ_EV_ERROR:
                    print('EV_ERROR: ' + os.strerror(event.data))

                else:
                    print('Received unknown event')
    finally:
        for fd in fdsWatched:
            if DEBUG: print('Closing file descriptor ' + str(fd))
            os.close(fd)

def usage():
    print('Usage:\n' + sys.argv[0] + ' <directory1 to monitor> <directory2 to monitor> ...')

if __name__ == "__main__":
    sys.exit(main())

