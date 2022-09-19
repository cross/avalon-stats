# vim:set et ts=4 sts=4 sw=4:
# Primary class for communicating with the socket API of miners
#

import socket
import select
import json
import sys
#import re
#from collections import OrderedDict
#import time
#import struct
#from datetime import timedelta
from pprint import pprint

class MinerAPI:
    def __init__(self, server, port):
        self.server = server
        self.port = port
        self.conn = None

    def open(self):
        self.conn = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        self.conn.connect((self.server,self.port))

    def json(self,command,params=None):
        """Build a JSON command string to be sent.
        Arguments:
            command - The command to be sent
            params - Command parameter(s) (optional)
        Returns:
            ???
        """
        d = {"command":command}
        if isinstance(params, str):
            d["param"] = params
        else:
            d["params"] = params
        return json.dumps(d)

    def conn(self):
        return self.conn

    def close(self):
        return self.conn.close()

    def hasdata(self, timeout):
        """Using select.select, return a boolean for whether there is data
        available to be read from our socket (self.conn)"""
        if not self.conn:
            raise RuntimeError(f"Cannot select on a closed {self.__class__.__name__}")
        myread,mywrite,myexcep = select.select([self.conn], [], [self.conn], timeout)
        if not myread and not myexcep:
            # Timeout, not ready.
            return False
        if self.conn in myexcep:
            raise RuntimeError("Exceptional condition on socket; unexpected!")
        return True

    def rawread(self):
        """Read all data from the connection."""
        if not self.conn:
            raise RuntimeError(f"Cannot read on a closed {self.__class__.__name__}")
        # Wait a few seconds to make sure something is available, if not,
        # return the expected empty string.
        if self.hasdata(3.0):
            buffer = self.conn.recv(4096).decode()
#            print(f"DEBUG: read {len(buffer)} bytes in first read")
        else:
            return ""
        done = False
        while not done:
            # (How long to wait here?)
            if self.hasdata(0.5):
                more = self.conn.recv(4096).decode()
                if not more:
                    done = True
                else:
                    buffer = buffer+more
            else:
                done = True

        # Remove a terminating null, if we see one.
        if buffer:
            if buffer[-1] == "\x00":
                buffer = buffer[:-1]
        return buffer

    def get_resp(self):
        """Retrieve JSON blob from connection and return a python object"""
        data = self.rawread()
        if not data:
            return None
        return json.loads(data)
    
    def send(self, data):
        """Send a JSON object across the connection."""
        return self.conn.sendall(data)


"""
def _api_command(command,param,server,port):
    s = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    print("Going to connect to socket")
    s.connect((server,port))
    print("connect returned, sending command")
    if param:
        cmdjsonstr = json.dumps({"command":command,"parameter":param})
    else:
        cmdjsonstr = json.dumps({"command":command})

    print(f"sending '{cmdjsonstr}'")
    s.sendall((cmdjsonstr+"\n").encode())
    s.shutdown(socket.SHUT_WR)
    print("waiting for response")
    response = json.loads(getresponse(s))
    s.close()
    print(f"Sent '{command}', got back: {response}")
    # Check that the response was structed as we expect.
#    if "+" not in command and 'STATUS' not in response:
#        print("Unrecognized response, no STATUS")
#        sys.exit(2)

    return response
"""
