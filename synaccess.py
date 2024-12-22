#!/usr/bin/python3
# vim:set et ts=4 sts=4 sw=4:
#
# This application provides a CLI interface for Synaccess netBooter switched
# [and metered] PDUs.  It was written originally for use with a netBooter™
# NP-0201DU but is expected to work with most/all netBooter™ B and DU series
# models.  It will need changes to work with the more modern Synaccess DX
# series or SynLink series PDUs.
#
# Chris Ross - © 2024

import socket
import json
import sys
import argparse
import requests
import re
from collections import OrderedDict
import time
import struct
import pickle
from datetime import datetime,timedelta

from SynaccessPDU import SynaccessPDU,get_status

from pprint import pprint






def gen_url(server,port=80):
    proto='http'
    if port == 443:
        proto="https"
    url = proto + '://' + server
    if port:
        url = url + ':' + str(port)
    url += '/'
    return url

# Do we need to keep state while in monitoring mode?  Often not, so only do
# that work if needed.
keep_state = None

#
# Program options
#
parser = argparse.ArgumentParser(description='Issue commands to a Synaccess PDU')
parser.add_argument('-s','--server','--host', default='127.0.0.1', help='API server name/address (host or host:port)')
parser.add_argument('-p','--port', type=int, default=80, help='API server port')
group = parser.add_mutually_exclusive_group()
group.add_argument('--status', action='store_true', help='show outlet status')
# Shame we can't have another group here, for monitor and log, but argparse
# doesn't cope with nested groups, at least not well enough.
group.add_argument('-m','--monitor', action='store_true', help='Begin monitoring mode (does not exit)', )
parser.add_argument('-l','--log', type=argparse.FileType('w'), help='log machine-readable data to FILE')
group.add_argument('--on', action='store_true', help='Turn the outlet group on')
parser.add_argument('--autoon', nargs='?', type=int, const=10, metavar='N', help='When monitoring, if the outlets are off for N minutes, turn them back on."')
group.add_argument('--off', action='store_true', help='Turn the outlet group off')
# TODO: Maybe --status should be allowed with the others?  No harm in printing
# status before taking requested action...
args = parser.parse_args()

# Build base API URL, and setup session object
apiurl = gen_url(args.server, args.port)
pdu = SynaccessPDU(apiurl)
pdu.auth=('admin','admin')

# Some validation that should likely be coded into argparse bits
if args.autoon:
    if not args.monitor:
        parser.error("AutoOn (--autoon) is only allowed while in monitoring mode.")
    keep_state = {}

# TODO: Do we want to get/check status always, and only report if args.status?
if args.status:
    if False: # Older code
        # Get status
        r = pdu.get('status.xml')
        if (r.status_code / 100) != 2:
            print(f"Error.  Failed to retrieve status, HTTP status code {r.status_code}")
        data = status_xml(r.text)
    else:
        data = get_status(pdu)

    for i,v in data['outlet_state'].items():
        print("Outlet #{} is {}".format(i+1,"on" if v else "off"))
    if 'temp' in data:
        print("Temperature is {}°C".format(data['temp']))
    if 'current' in data:
        print("Current draw is {}A".format(data['current']))

    sys.exit(0)

if args.on or args.off:
    # These commands come from the WebAPI, and are not the same as the
    # coded commands listed in the HTTP API documentation at
    # https://static1.squarespace.com/static/54d27fb4e4b024eccdd9e569/t/651d79e2e2de6d3883208352/1696430563393/1094_NPStartup_V20.pdf
    # I don't know why that doc lists only a small subset, and with an
    # alternate style, but these ones I've scraped from the device U/I
    # work just fine.
    if args.on:
        cmd={ 'grp': 0 }
        reqstate="on"
    else:
        cmd={ 'grp': 30 }
        reqstate="off"
    r = pdu.get('cmd.cgi', params=cmd)
    if (r.status_code / 100) != 2:
        print(f"Error.  Failed to set group power, HTTP status code {r.status_code}")
        pprint(r.text)
        sys.exit(1)
    #pprint(r.text)
    resp = r.text.strip()
    #pprint(resp)
    if resp == '$A0':
        print(f"Outlet group has been powered {reqstate}.")
    else:
        print("Error.  Failed to retrieve status, API returned {} ({})".format(resp.text, str(resp)))

if args.monitor:
    timefmt="%Y-%m-%d %T"
    # TODO: Make period adjustable
    delay = 10
    call_time=time.time()
    while True:
        try:
            data = get_status(pdu)
        except requests.exceptions.ConnectionError as e:
            print("[{}] WARNING ConnectionError, skipping until next run.\n\
                    [{}] WARNING Detail: {}".format(
                    datetime.now().strftime(timefmt),
                    datetime.now().strftime(timefmt), e))
            # No catch of KeyboardInterrupt here.  :-/  How to fix?
            call_time = call_time + delay
            # in case more time has elapsed, skip until the next even run point
            while call_time < time.time():
                call_time = call_time + delay
            time.sleep(call_time - time.time())
            continue
        outlet_state_str = " ".join(["On" if v else "Off" for i,v in data['outlet_state'].items()])
        if keep_state != None and 'outlet_state' in keep_state and keep_state['outlet_state'] == data['outlet_state'] and 'outlet_state_change' in keep_state:
            ago= datetime.now() - keep_state['outlet_state_change']
            if ago > timedelta(days=6*30):
                fmt="%b-%Y"
            elif ago > timedelta(days=2*30):
                fmt="%d-%b-%Y"
            elif ago > timedelta(days=8):
                fmt="%d-%b"
            elif ago > timedelta(days=2):
                fmt="%d-%b %H:%M"
            elif ago > timedelta(hours=8):
                fmt="%a %H:%M"
            else:
                fmt="%H:%M"
            outlet_state_str += " (since {})".format(keep_state['outlet_state_change'].strftime(fmt))
        print("[{}] Outlets: {}  Temp: {}°C  Current: {}A".format(
            datetime.now().strftime(timefmt), outlet_state_str,
            data['temp'], data['current']))
        if keep_state != None:
            if 'outlet_state' not in keep_state or \
                    data['outlet_state'] != keep_state['outlet_state']:
                keep_state['outlet_state_change'] = datetime.now()
            # Python 3.9+
            #keep_state = keep_state | data
            # Python 3.5+
            keep_state = {**keep_state, **data}
        if args.log:
            print(f"(should be logging to {args.log})")
        try:
            call_time = call_time + delay
            if call_time > time.time():
                time.sleep(call_time - time.time())
            else:
                call_time = time.time()
        except KeyboardInterrupt:
            print() # drop to new line after a ^C
            break
        if args.autoon:
            time_since = datetime.now() - keep_state['outlet_state_change']
#            print("Outlet status is {}, last changed {} ago.".format(data['outlet_state'], time_since), flush=True)
            if False in keep_state['outlet_state'].values() and time_since > timedelta(minutes=args.autoon):
                s='s' if args.autoon != 1 else ''
                print(f"Powering on the outlet group (off more than {args.autoon} minute{s})")
                r = pdu.get('cmd.cgi', params={'grp': 0})
                if (r.status_code / 100) != 2:
                    print(f"Error.  Failed to power on the outlet group, HTTP status code {r.status_code}")
                    pprint(r.text)
                    # TODO: Should sleep til next call_time.
                    continue
                    #pprint(r.text)
                    resp = r.text.strip()
                    #pprint(resp)
                    if resp == '$A0':
                        print(f"Outlet group has been powered on.")
                    else:
                        print("Error.  Didn't understand response, API returned {} ({})".format(resp.text, str(resp)))
#            elif args.autoon:
#                print("autoon, state is {}".format(keep_state['outlet_state'].values()))

sys.exit(0)

now = int(time.time())
if not response or 'result' not in response or response['result'] != "pong":
    raise RuntimeError("Unexpected response to miner_ping: {}".format(response))
