# vim:set et ts=4 sts=4 sw=4:
# Primary class for communicating with the socket API of miners
#

import socket
import select
import json
#import re
#from collections import OrderedDict
#import time
#import struct
#from datetime import timedelta
from pprint import pprint
from urllib.parse import urlsplit
from typing import final

class MinerException(Exception):
    """Exception class for miner-related errors that can be handled by the caller.

    This exception can be used to signal various error conditions from the miner
    that may be recoverable or require specific handling (e.g., retryable errors).

    Attributes:
        error_type: Type of error - 'fatal', 'warning', 'retry_short', 'retry_long'
        message: The error message
    """

    # Error type constants
    FATAL = 'fatal'
    WARNING = 'warning'
    RETRY_SHORT = 'retry_short'  # Retry right away or after brief pause
    RETRY_LONG = 'retry_long'    # Wait some time before retrying

    def __init__(self, message, error_type=FATAL):
        """Initialize MinerException.

        Args:
            message: The error message
            error_type: One of FATAL, WARNING, RETRY_SHORT, or RETRY_LONG
        """
        super().__init__(message)
        self.message = message
        self.error_type = error_type

    def is_retryable(self):
        """Return True if this error suggests a retry."""
        return self.error_type in (self.RETRY_SHORT, self.RETRY_LONG)

    def is_fatal(self):
        """Return True if this is a fatal error."""
        return self.error_type == self.FATAL

    def is_warning(self):
        """Return True if this is just a warning."""
        return self.error_type == self.WARNING

class MinerAPI:
    @staticmethod
    @final
    def parse_host(hostspec, defaultport=None):
        """Parse a host:port specification.

        This method is marked as final and should not be overridden by subclasses.
        We may allow subclass-specific parsing in the future if needed.

        Args:
            hostspec: String in format "host:port" or just "host"
            defaultport: Default port if not specified (currently unused)

        Returns:
            Tuple of (hostname, port)
        """
        r = urlsplit('//'+hostspec)
        return (r.hostname, r.port)

    def __init__(self, server, port=None):
        if port is None or port == 0:
            # Separate out a host:port spec
            host,port = __class__.parse_host(server)
            self.server = host
            self.port = port
            if not self.port:
                raise ValueError("Port is required, but wasn't specified")
        else:
            self.server = server
            self.port = port
        self.conn = None

    def open(self):
        if ':' in self.server:
            self.conn = socket.socket(socket.AF_INET6,socket.SOCK_STREAM)
        else:
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

    def is_connected(self):
        """Check if the connection is open and writable.

        Returns:
            Boolean indicating if connection is open and ready for writing
        """
        if not self.conn:
            return False
        try:
            # Check if socket has a valid file descriptor (closed sockets return -1)
            if self.conn.fileno() == -1:
                return False
            # Check if socket is writable (can send data)
            _, writable, _ = select.select([], [self.conn], [], 0)
            return bool(writable)
        except (OSError, AttributeError, ValueError):
            return False

    def close(self):
        if self.conn:
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
        try:
            return json.loads(data)
        except json.JSONDecodeError as e:
            print(f"Unable to object from string, is it valid JSON?\n-----\n{data}\n-----")
            return None
    
    def send(self, data):
        """Send a JSON object across the connection."""
        # TODO: Check that data is a bytes-like object.
        return self.conn.sendall(data)

    def send_command(self, command, params=None):
        """
        Arguments:
            command - command to be sent (string)
            params - Command parameter(s) (optional) (string or sequence)
        Returns:
            ???
        """
        jsondata = self.json(command,params) + "\n";
        jsondata = jsondata.encode()
        return self.send(jsondata)
