#!/usr/bin/python3
# vim:set et ts=4 sts=4 sw=4:
#
# This application provides a CLI interface for Synaccess netBooter switched
# [and metered] PDUs.  It was written originally for use with a netBooter™
# NP-0201DU but is expected to work with most/all netBooter™ B and DU series
# models.  It will need changes to work with the more modern Synaccess DX
# series or SynLink series PDUs.
#
# Chris Ross - © 2024-2025

import socket
import json
import sys
import argparse
import requests
import re
from collections import OrderedDict
import time
import math
import struct
import pickle
from datetime import datetime,timedelta

from SynaccessPDU import SynaccessPDU,get_status,status_xml

from pprint import pprint

# Time format used in output/logging messages.
TIMEFMT = "%Y-%m-%d %T"



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
subparsers = parser.add_subparsers(dest='command', required=True, help='Command to run')
subparsers.add_parser('status', help='Show outlet status')
monitor_parser = subparsers.add_parser('monitor', help='Begin monitoring mode (does not exit)')
monitor_parser.add_argument('-i', '--interval', type=int, default=15, metavar='SECS',
    help='Delay between iterations in seconds (default: 15)')
monitor_parser.add_argument('--autoon', nargs='?', type=int, const=10, metavar='N',
    help='If the outlets are off for N minutes, turn them back on (default: 10)')
monitor_parser.add_argument('-l', '--log', type=argparse.FileType('w'), metavar='FILE',
    help='Log machine-readable data to FILE')

subparsers.add_parser('on', help='Turn the outlet group on')
subparsers.add_parser('off', help='Turn the outlet group off')

help_parser = subparsers.add_parser('help', help='Show help (same as --help)')
help_parser.add_argument('topic', nargs='?', choices=['status', 'monitor', 'on', 'off'],
    help='Command to show help for')

args = parser.parse_args()

if args.command == 'help':
    if args.topic is None:
        parser.print_help()
    else:
        subparsers.choices[args.topic].print_help()
    sys.exit(0)

# Build base API URL, and setup session object
apiurl = gen_url(args.server, args.port)
pdu = SynaccessPDU(apiurl, timefmt=TIMEFMT)

if args.command == 'monitor' and getattr(args, 'autoon', None):
    keep_state = {}

# TODO: Do we want to get/check status always, and only report if status?
if args.command == 'status':
    try:
        data = get_status(pdu)
    except requests.exceptions.ConnectionError as e:
        print("[{}] WARNING ConnectionError: {}".format(
                datetime.now().strftime(TIMEFMT), e))
        # TODO: Should I implement a small retry loop here?
        sys.exit(1)
    except (requests.exceptions.ReadTimeout, requests.exceptions.Timeout) as e:
        print("[{}] WARNING Timeout ({}): {}".format(
                datetime.now().strftime(TIMEFMT), type(e).__name__, e))
        sys.exit(1)

    for i,v in data['outlet_state'].items():
        print("Outlet #{} is {}".format(i+1,"on" if v else "off"))
    if 'temp' in data:
        print("Temperature is {}°C".format(data['temp']))
    if 'current' in data:
        print("Current draw is {}A".format(data['current']))

    sys.exit(0)

if args.command in ('on', 'off'):
    # These commands come from the WebAPI, and are not the same as the
    # coded commands listed in the HTTP API documentation at
    # https://static1.squarespace.com/static/54d27fb4e4b024eccdd9e569/t/651d79e2e2de6d3883208352/1696430563393/1094_NPStartup_V20.pdf
    # I don't know why that doc lists only a small subset, and with an
    # alternate style, but these ones I've scraped from the device U/I
    # work just fine.
    if args.command == 'on':
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

if args.command == 'monitor':
    delay = args.interval
    while True:
        try:
            data = get_status(pdu)
        except requests.exceptions.ConnectionError as e:
            print("[{}] WARNING ConnectionError, skipping until next run.\n\
[{}] WARNING Detail: {}".format(
                    datetime.now().strftime(TIMEFMT),
                    datetime.now().strftime(TIMEFMT), e))
            # Sleep until next aligned timestamp (even multiple of delay since epoch)
            now = time.time()
            next_run = (math.floor(now / delay) + 1) * delay
            time.sleep(max(0, next_run - now))
            continue
        except (requests.exceptions.Timeout,requests.exceptions.ReadTimeout) as e:
            print("[{}] WARNING Timeout ({}): {}".format(
                  datetime.now().strftime(TIMEFMT), type(e).__name__, e))
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
            datetime.now().strftime(TIMEFMT), outlet_state_str,
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
            # Sleep until next aligned timestamp (even multiple of delay since epoch)
            now = time.time()
            next_run = (math.floor(now / delay) + 1) * delay
            time.sleep(max(0, next_run - now))
        except KeyboardInterrupt:
            print() # drop to new line after a ^C
            break
        if getattr(args, 'autoon', None):
            time_since = datetime.now() - keep_state['outlet_state_change']
#            print("Outlet status is {}, last changed {} ago.".format(data['outlet_state'], time_since), flush=True)
            if False in keep_state['outlet_state'].values() and time_since > timedelta(minutes=args.autoon):
                s='s' if args.autoon != 1 else ''
                print(f"Powering on the outlet group (off more than {args.autoon} minute{s})")
                r = pdu.get('cmd.cgi', params={'grp': 0})
                if (r.status_code / 100) != 2:
                    print(f"Error.  Failed to power on the outlet group, HTTP status code {r.status_code}")
                    pprint(r.text)
                    # TODO: Should sleep til next aligned run.
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
