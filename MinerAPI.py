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
        jsondata = self.json(command,params) + "\n";
        jsondata = jsondata.encode()
        return self.send(jsondata)

# CGMiner protocol implementation
class CGMiner(MinerAPI):
    """Subclass for CGMiner protocol handling.

    This class implements the cgminer API protocol over the TCP connection
    provided by the base MinerAPI class.
    """

    def detect_miner_type(self):
        """Detect the miner type by querying the version command.

        Returns:
            String identifying miner type ('bosminer', 'cgminer', 'unknown')
        """
        try:
            response = self.api_command('version')
            version_data = response.get('VERSION', [{}])[0]

            if 'BOSer' in version_data:
                return 'bosminer'
            elif 'CGMiner' in version_data:
                return 'cgminer'
            else:
                return 'unknown'
        except (KeyError, IndexError, TypeError):
            return 'unknown'

    def api_command(self, command, param=None):
        """Execute an API command and return the response.

        Args:
            command: Either a string command (e.g., "summary", "stats") or a list/tuple
                    of commands to be combined (e.g., ["summary", "stats"] or ("devs", "temps", "fans"))
            param: Optional parameter for the command

        Returns:
            The raw JSON response from the miner. For combined commands, the response
            will have separate keys for each command part.

        Raises:
            RuntimeError: If no response is received or expected keys are missing
        """
        # Convert list/tuple to combined command string
        if isinstance(command, (list, tuple)):
            command_str = '+'.join(command)
            expected_keys = list(command)
        else:
            command_str = command
            expected_keys = None

        self.send_command(command_str, param)
        response = self.get_resp()

        if not response:
            raise RuntimeError(f"No response returned for command: {command_str}")

        # Check that the response was structured as we expect.
        if "+" not in command_str and 'STATUS' not in response:
            raise MinerException("Unrecognized response, no STATUS")

        # For combined commands, validate that all expected keys are present
        if expected_keys:
            for key in expected_keys:
                if key not in response:
                    raise RuntimeError(f"No {key} returned for '{command_str}' request")

        return response

    def execute_command(self, command, param=None, max_retry_duration=300,
                       initial_delay_short=1, initial_delay_long=10, max_delay=60):
        """Execute an API command with automatic retry logic and response parsing.

        This is the high-level method that most code should use. It handles:
        - Sending the command via api_command()
        - Parsing responses via _handle_response()
        - Automatic retry with linear backoff on retryable errors
        - Connection reopening on retry

        Args:
            command: Either a string command or list/tuple of commands
            param: Optional parameter for the command
            max_retry_duration: Maximum time in seconds to retry (default: 300)
            initial_delay_short: Initial delay for RETRY_SHORT errors (default: 1s)
            initial_delay_long: Initial delay for RETRY_LONG errors (default: 10s)
            max_delay: Maximum delay between retries (default: 60s)

        Returns:
            For single command: parsed data dict
            For combined commands: dict with keys for each command containing parsed data

        Raises:
            MinerException: On non-retryable error or max retry duration exceeded
            RuntimeError: On other errors
        """
        import time

        retry_start_time = time.time()
        attempt = 0

        # Determine if this is a combined command
        is_combined = isinstance(command, (list, tuple))
        command_list = list(command) if is_combined else [command]

        while True:
            try:
                # Ensure we have a usable connection
                # (cgminer/bosminer only gives one answer per connection)
                if not self.is_connected():
                    self.close() # Might be unnecessary?
                    self.open()

                # Send command and get raw response
                response = self.api_command(command, param)

                # Parse responses
                if is_combined:
                    # Parse each part of combined command
                    result = {}
                    for cmd in command_list:
                        data, _ = self._handle_response(response[cmd][0], cmd)
                        result[cmd] = data
                else:
                    # Parse single command response
                    result = self._handle_response(response, command)[0]

                # Close connection after successful command
                # (cgminer/bosminer only gives one answer per connection)
                # TODO: Investigate keeping connection open and reusing it for multiple commands
                # This would require tracking connection state and detecting when server closes its end
                self.close()
                return result

            except MinerException as e:
                if not e.is_retryable():
                    # Fatal error or warning, don't retry
                    print(f"Non-retryable MinerException for command {command}: {e}")
                    raise

                elapsed = time.time() - retry_start_time
                if elapsed >= max_retry_duration:
                    print(f"MinerException for command {command} after {elapsed:.1f}s (max {max_retry_duration}s reached): {e}. Giving up.")
                    raise

                # Calculate linear back-off delay based on error type
                if e.error_type == MinerException.RETRY_SHORT:
                    base_delay = initial_delay_short
                elif e.error_type == MinerException.RETRY_LONG:
                    base_delay = initial_delay_long
                else:
                    base_delay = initial_delay_short  # Default fallback

                # Linear back-off: delay increases by base_delay each attempt, capped at max_delay
                delay = min(base_delay * (attempt + 1), max_delay)

                # Don't sleep longer than remaining time
                remaining_time = max_retry_duration - elapsed
                delay = min(delay, remaining_time)

                print(f"MinerException for command {command} on attempt {attempt + 1} ({elapsed:.1f}s elapsed): {e}. Retrying in {delay:.1f} seconds...")
                time.sleep(delay)
                attempt += 1

    def _handle_response(self, data, command):
        """Internal method to handle the response to an API request. If the response indicates
        other than successful, report and exit. Otherwise, return the relevant
        portion of the data, if we recognize it, based on "Code" in response.

        Returns:
            Tuple of (result_data, was_recognized) where was_recognized is True if
            the response code was understood, False otherwise. This allows subclasses
            to handle additional codes without warning messages.
        """
        import re
        import sys

        if not data:
            raise RuntimeError(f"No response returned for command: {command}")

        # Check that the response was structured as we expect.
        if "+" not in command and 'STATUS' not in data:
            print("Unrecognized response, no STATUS")
            sys.exit(2)

        status = data['STATUS'][0]

        # Handle 'S' or 'E', appropriately. So far I haven't seen others.
        #   STATUS=X Where X is one of:
        #     W - Warning
        #     I - Informational
        #     S - Success
        #     E - Error
        #     F - Fatal (code bug)
        if status['STATUS'] == "E":
            errmsg = status['Msg']
            # Pattern match against different error messages to handle them appropriately
            # Define patterns and their handling behavior (error_type from MinerException)
            error_patterns = [
                (r'Not ready', MinerException.RETRY_SHORT),
                (r'Disconnected', MinerException.RETRY_LONG),
                # Add more patterns here as needed, e.g.:
                # (r'Connection timeout', MinerException.RETRY_SHORT),
                # (r'Busy', MinerException.RETRY_LONG),
                # (r'Invalid command', MinerException.FATAL),
            ]

            # Check error message against each pattern
            for pattern, error_type in error_patterns:
                if re.search(pattern, errmsg, re.IGNORECASE):
                    # Raise exception with appropriate error type
                    raise MinerException(f"Error for command {command}: {errmsg}", error_type)

            # If no pattern matched, fall through to default error handling
            print("Failed to execute command {}: {}".format(command, status['Msg']))
            sys.exit(3)

        if status['STATUS'] != "S":
            print("Unexpected status '{}': {}".format(status['STATUS'], status['Msg']))
            sys.exit(4)

        # Handle standard response codes
        if status['Code'] == 70:    # MSG_MINESTATS:
            return (data['STATS'], True)
        elif status['Code'] == 11:  # MSG_SUMM
            return (data['SUMMARY'][0], True)
        elif status['Code'] == 9:   # MSG_DEVS
            return (data['DEVS'], True)
        else:
            # Return data and indicate it was not recognized
            return (data, False)

# Make some subclasses that need to override certain things
class KawpowMiner(MinerAPI):
    def json(self,command,params=None):
        """Build a JSON command string to be sent.
        Arguments:
            command - The command to be sent
            params - Command parameter(s) (optional)
        Returns:
            ???
        """
        d = {"id":0,"jsonrpc":"2.0","method":command}
        if isinstance(params, str):
            d["param"] = params
        else:
            d["params"] = params
        return json.dumps(d)

class BOSminer(CGMiner):
    """Subclass for BOSminer (Braiins OS) specific API handling.

    Extends CGMiner to add BOSminer-specific response codes (TEMPS and FANS).
    """

    def _handle_response(self, data, command):
        """Handle BOSminer-specific response codes.

        Extends the base _handle_response to add BOSminer-specific response codes
        (TEMPS and FANS).
        """
        # Call parent _handle_response first for error handling and standard codes
        result, was_recognized = super()._handle_response(data, command)

        # If parent didn't recognize it, check for BOSminer-specific codes
        if not was_recognized and 'STATUS' in data:
            status = data['STATUS'][0]
            if status['Code'] == 201:  # TEMPS
                return (data['TEMPS'], True)
            elif status['Code'] == 202:  # FANS
                return (data['FANS'], True)
            else:
                # Still not recognized, print warning and return data
                print("WARNING: Don't recognize response with code {}, returning whole response data.".format(status['Code']))
                return (data, False)

        # Parent recognized it, return the result
        return (result, was_recognized)

    def get_device_info(self, max_retry_duration=300, initial_delay_short=1,
                       initial_delay_long=10, max_delay=60):
        """Get device, temperature, and fan information from BOSminer with retry logic.

        Args:
            max_retry_duration: Maximum time in seconds to retry (default: 300)
            initial_delay_short: Initial delay for RETRY_SHORT errors (default: 1s)
            initial_delay_long: Initial delay for RETRY_LONG errors (default: 10s)
            max_delay: Maximum delay between retries (default: 60s)

        Returns:
            Dict with 'devs_data', 'temps_data', and 'fans_data' keys containing processed data.

        Raises:
            MinerException: If non-retryable error or max retry duration exceeded
        """
        # Use execute_command which handles retry logic automatically
        data = self.execute_command(
            ['devs', 'temps', 'fans'],
            max_retry_duration=max_retry_duration,
            initial_delay_short=initial_delay_short,
            initial_delay_long=initial_delay_long,
            max_delay=max_delay
        )

        return {
            'devs_data': data['devs'],
            'temps_data': data['temps'],
            'fans_data': data['fans']
        }

    def format_device_stats(self, devs_data, temps_data, fans_data, brief=False):
        """Format device statistics for display.

        Args:
            devs_data: List of device data dicts
            temps_data: List of temperature data dicts
            fans_data: List of fan data dicts
            brief: Boolean for brief output mode

        Returns:
            List of formatted strings for output
        """
        output_lines = []

        # Create a dictionary to match temps by ID for efficient lookup
        temps_by_id = {t['ID']: t for t in temps_data}

        # Process device data
        for d in devs_data:
            avmhs = float(d['Nominal MHS'])
            if avmhs > 1200000:
                avspeed = ("TH/s", avmhs/1024.0/1024.0)
            elif avmhs > 1100:
                avspeed = ("GH/s", avmhs/1024.0)
            else:
                avspeed = ("MH/s", avmhs)

            # Look up temperature data by matching ID
            temp_data = temps_by_id.get(d['ID'])
            if temp_data:
                temp = float(temp_data['Chip'])
                board_temp = float(temp_data['Board'])
                temp_str_brief = f"{temp:.1f}°C"
                temp_str_verbose = f"{board_temp:.1f}/{temp:.1f}°C"
            else:
                # No temperature data available for this device ID
                temp_str_brief = "N/A°C"
                temp_str_verbose = "(no temp data)"

            if brief:
                output_lines.append(f" ; #{d['ID']}: {d['MHS 1m']/1024.0:.3f}/{d['Nominal MHS']/1024.0:.3f} {temp_str_brief}")
            else:
                output_lines.append(f"    #{d['ID']}: Nominal Hashrate: {avspeed[1]:.3f} {avspeed[0]}, {temp_str_verbose}")

        # Process fan data
        for f in fans_data:
            if brief:
                if f['RPM'] > 0:
                    output_lines.append(f" ; F{f['ID']}: {f['RPM']}rpm {f['Speed']}%")
            else:
                output_lines.append(f"    Fan {f['ID']:1} : {f['RPM']:5d} rpm; {f['Speed']}%")

        return output_lines

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
