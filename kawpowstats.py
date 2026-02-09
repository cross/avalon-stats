#!/usr/bin/python3
# vim:set et ts=4 sts=4 sw=4:
#
# Contact a kawpowminer process and report information about its state.

import socket
import json
import sys
import argparse
import re
from collections import OrderedDict
import time
import struct
import pickle
from datetime import timedelta
import humanize
from pprint import pprint
from Miners import KawpowMiner

def handle_response(data):
    """Handle the response to an API request.  If the response indicates
    other than successful, report and exit.  Otherwise, return the relevant
    portion of the data, if we recognize it, based on "Code" in response."""
    # TODO: Look for error responses of known format

    if not data or 'result' not in data:
        print("Failed to execute command, response was: {}".format(data))
        sys.exit(3)

    # Check the things we're interested in
    result = data['result']
#    pprint(result)
    # TODO: How to we recognize responses to different commands?

    # TODO:  Return things, don't just print them.
    ret = {}
    if 'host' in result:
#        print("{} running on {} for {}".format(*map(result['host'].get, ['version','name']),timedelta(seconds=result['host']['runtime'])))
        ret = { key:result['host'][key] for key in ['name','runtime','version']}
    if 'connection' in result:
#        print("Connected?  {}".format(result['connection']['connected']))
        ret['connected'] = result['connection']['connected']
    if 'devices' in result:
        print(f"Reporting on {len(result['devices'])} devices")
    if 'mining' in result:
        # hashrate is a string, containing a hexadecimal value (hash/sec)
        ret['hashrate'] = int(result['mining']['hashrate'],0)
        ret['shares'] = result['mining']['shares']
        """
        if hashrate < 1200:
            hrstr = "{} hs".format(hashrate)
        elif hashrate < 1100000:
            hrstr = "{:.2f} Khs".format(hashrate/1024.0)
        elif hashrate < 1100000000:
            hrstr = "{:.2f} Mhs".format(hashrate/1024.0/1024.0)
        elif hashrate < 1100000000000:
            hrstr = "{:.2f} Ghs".format(hashrate/1024.0/1024.0/1024.0)
        shares = result['mining']['shares']
#        print("We're seeing a hashrate of {}, {} shares have been accepted ({:.2f}/hour)".format(hrstr, shares[0], (shares[0]/(result['host']['runtime']/3600))))
        """
    else:
        return RuntimeError("Did not get a 'mining' data block in response")

    return ret

parser = argparse.ArgumentParser(description='Retrieve periodic status from cgminer.')
parser.add_argument('-s','--server','--host', default='127.0.0.1', help='API server name/address (host or host:port)')
parser.add_argument('-p','--port', type=int, default=3333, help='API server port')
parser.add_argument('-g','--graphite', metavar='SERVER', help='Format data for graphite, server:host or "-" for stdout')
args = parser.parse_args()

# TODO: Should make an argparser for this
if args.graphite:
    # Parse the argument, which is expected to be a host:port specification
    # (but, other things also allowed for unusual run modes)
    # TODO: This gets things wrong sometimes.  Should likely improve it.
    hostportpat = re.compile(r'(\d+\.\d+\.\d+\.\d+|\[(?:[0-9a-fA-F]+)?:?(?:\:[0-9a-fA-F]*)+\]|[\w\-_]+(?:\.[\w\-_]+)*):(\d+)')
    m = hostportpat.match(args.graphite)
    if m:
        hostspec = m.group(1)
        if hostspec[0] == '[' and hostspec[-1] == ']':
            hostspec = hostspec[1:-1]
        port = int(m.group(2))
        print("Got host spec {}, port {}, for graphite server".format(hostspec,port))
        # TODO: Should verify ability to connect here, before polling cgminer
    elif args.graphite == "-":
        hostspec = None
        print("Should output graphite data to stdout")
    else:
        print("Got non host:port value {} for graphite server".format(args.graphite))
        sys.exit(6)

miner = KawpowMiner(args.server,args.port)
miner.open()
miner.send_command("miner_ping")
response = miner.get_resp()
now = int(time.time())
if not response or 'result' not in response or response['result'] != "pong":
    raise RuntimeError("Unexpected response to miner_ping: {}".format(response))

# Issue the real query to get stats
miner.send_command("miner_getstatdetail")
response = miner.get_resp()
#pprint(response)   # The whole shebang of stat details
if not response or 'result' not in response:
    raise RuntimeError("Unexpected response to miner_getstatdetail: {}".format(response))

respdata = handle_response(response) # Will exit on failure, return summary dict on success

# XXX Lots more to fix (or remove)

prefix = 'collectd.crosstest.gen2'
if args.graphite:
    sectprefix = prefix + '.summary'
    records = [ ('{}.elapsed'.format(sectprefix),(now,int(respdata['runtime']))),
                ('{}.accepted'.format(sectprefix),(now,int(respdata['shares'][0]))),
                ('{}.rejected'.format(sectprefix),(now,int(respdata['shares'][1]))),
              ]
    for k,v in [(x,respdata[x]) for x in respdata.keys() if x[0:3] == "MHS"]:
        records.append(('{}.{}'.format(sectprefix,".".join(k.split())).lower(),(now,int(v))))
else:
    #pprint(respdata)
    print("Summary:")
    print("  Running for: {:>8s}".format(str(timedelta(seconds=respdata['runtime']))))
    if respdata['hashrate'] < 1100000:
        print("  KHS av     : {:8.2f}".format(respdata['hashrate']/1000))
    elif respdata['hashrate'] > 1100000000:
        print("  GHS av     : {:8.2f}".format(respdata['hashrate']/1000/1000/1000))
    else:
        print("  MHS av     : {:8.2f}".format(respdata['hashrate']/1000/1000))
    if respdata['shares'][0] > 0:
        sharePerHour = respdata['shares'][0] / (respdata['runtime'] / 3600)
        sharePerMin = respdata['shares'][0] / (respdata['runtime'] / 60)
        if sharePerMin < 1 and sharePerHour > 1:
            rateStr = "{:.2f} per hour".format(sharePerHour)
        elif sharePerMin >= 1:
            rateStr = "{:.2f} per minute".format(sharePerMin)
        else: # sharePerHour <= 1
            # For really slow cases, switch it to time/share
            rateStr = "avg {} per share".format(humanize.naturaldelta(timedelta(seconds=int(respdata['runtime']/respdata['shares'][0]))))
        print("  Accepted   : {:8d} ({})".format(respdata['shares'][0], rateStr))
    else:
        print("  Accepted   : {:8d}".format(respdata['shares'][0]))
    print("  Rejected   : {:8d}".format(respdata['shares'][1]))
    if respdata['shares'][0]:
        print("  Last share : {:>8s} ago".format(str(timedelta(seconds=respdata['shares'][3]))))
    else:
        print("  Last share : {:>8s}".format("never"))

if args.graphite:
    if hostspec:
        # TODO Add graphite goo.  Or don't, we're not doing graphite anymore.
        pass
    else:
        pprint(records)

# TODO: Print pool/work information?

sys.exit(0);
