#!/usr/bin/python3
# vim:set et ts=4 sts=4 sw=4:
#

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
from pprint import pprint
from MinerAPI import KawpowMiner

def handle_response(data):
    """Handle the response to an API request.  If the repsponse indicates
    other than successful, report and exit.  Otherwise, return the relevant
    portion of the data, if we recognize it, based on "Code" in response."""
    # TODO: Look for error responses of known format

    if not data or 'result' not in data:
        print("Failed to execute command, response was: {}".format(data))
        sys.exit(3)

    # Check the things we're interested in
    result = data['result']
    # TODO: How to we recognize responses to different commands?

    # TODO:  Return things, don't just print them.
    if 'host' in result:
        print("{} running on {} for {}".format(*map(result['host'].get, ['version','name']),timedelta(seconds=result['host']['runtime'])))
    if 'connection' in result:
        print("Connected?  {}".format(result['connection']['connected']))
    if 'devices' in result:
        print(f"Reporting on {len(result['devices'])} devices")
    if 'mining' in result:
        hashrate = int(result['mining']['hashrate'],0)
        if hashrate < 1200:
            hrstr = "{} hs".format(hashrate)
        elif hashrate < 1100000:
            hrstr = "{:.2f} Khs".format(hashrate/1024.0)
        elif hashrate < 1100000000:
            hrstr = "{:.2f} Mhs".format(hashrate/1024.0/1024.0)
        elif hashrate < 1100000000000:
            hrstr = "{:.2f} Ghs".format(hashrate/1024.0/1024.0/1024.0)
        shares = result['mining']['shares']
        print("We're seeing a hashrate of {}, {} shares have been accepted ({:.2f}/hour)".format(hrstr, shares[0], (shares[0]/(result['host']['runtime']/3600))))

parser = argparse.ArgumentParser(description='Retrieve periodic status from cgminer.')
parser.add_argument('-s','--server','--host', default='127.0.0.1', help='API server name/address')
parser.add_argument('-p','--port', type=int, default=4028, help='API server port')
parser.add_argument('-g','--graphite', metavar='SERVER', help='Format data for graphite, server:host or "-" for stdout')
args = parser.parse_args()

# Wrapper functions, defined here so they can default to the server/port args
def api_get_summary(server=args.server,port=args.port):
    return _api_command("summary",None,server,port)
def api_get_stats(server=args.server,port=args.port):
    return _api_command("stats",None,server,port)
def api_get_data(server=args.server,port=args.port):
    combined_results = _api_command("summary+stats",None,server,port)
    if 'summary' not in combined_results:
        raise RuntimeError("No summary returned for 'summary+stats' request")
    if 'stats' not in combined_results:
        raise RuntimeError("No stats returned for 'summary+stats' request")
    return combined_results

# TODO: Should make an argparser for this
if args.graphite:
    # Parse the argument, which is expected to be a host:port specification
    # (but, other things also allowed for unusual run modes)
    # TODO: This gets things wrong somtimes.  Should likely improve it.
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
#pprint(response)
if not response or 'result' not in response or response['result'] != "pong":
    raise RuntimeError("Unexpected response to miner_ping: {}".format(response))

# Issue the real query to get stats
miner.send_command("miner_getstatdetail")
response = miner.get_resp()
if not response or 'result' not in response:
    raise RuntimeError("Unexpected response to miner_getstatdetail: {}".format(response))

respdata = handle_response(response) # Will exit on failure, return summary dict on success
pprint(respdata)

# XXX Lots more to fix (or remove)

sys.exit(0);

prefix = 'collectd.crosstest'
if args.graphite:
    sectprefix = prefix + '.summary'
    records = [ ('{}.elapsed'.format(sectprefix),(now,int(respdata['Elapsed']))),
                ('{}.accepted'.format(sectprefix),(now,int(respdata['Accepted']))),
                ('{}.rejected'.format(sectprefix),(now,int(respdata['Rejected']))),
              ]
    for k,v in [(x,respdata[x]) for x in respdata.keys() if x[0:3] == "MHS"]:
        records.append(('{}.{}'.format(sectprefix,".".join(k.split())).lower(),(now,int(v))))
else:
    #pprint(respdata)
    print("Summary:")
    print("  Running for: {}".format(timedelta(seconds=respdata['Elapsed'])))
    print("  GHS av     : {:7.2f}".format(respdata['MHS av']/1024.0))
    print("  Accepted   : {:7d}".format(respdata['Accepted']))
    print("  Rejected   : {:7d}".format(respdata['Rejected']))

# TODO: Print pool/work information?

# Break-out and report per-device stats
respdata = handle_response(response['stats'][0],"stats") # Will exit on failure, return stats list on success
#pprint(respdata)

(stats0,stats1) = respdata
stats0 = restructure_stats0(stats0)
#pprint(stats0)

prefix = 'collectd.crosstest'
if not args.graphite:
    print("Device stats:")
#else:
#    records = []

for i in stats0['MM']:
    if args.graphite:
        sectprefix = prefix + '.stats.mm.{}'.format(i['DNA'])
        records.append(('{}.fan'.format(sectprefix),(now,int(i['Fan']))))
        records.append(('{}.ghsmm'.format(sectprefix),(now,float(i['GHSmm']))))
        records.append(('{}.ghs5m'.format(sectprefix),(now,float(i['GHS5m']))))
    else:
        print("MM {:4s}: {:>10s}  {}/{}".format(i['DNA'][-4:],"Ghz (?/5m)",i['GHSmm'],i['GHS5m']))
        print("{:7}: {:>10s}  {}rpm".format("","Fan",i['Fan']))
    # I'm not sure what 'Temp' 'Temp0' and 'Temp1' each are, but 'Temp' looks
    # to be much lower, so maybe enclosure?  I'm going to average 'Temp0' and
    # 'Temp1' to be the number I think I'm looking for, but that's just a
    # random guess.
    temp = (float(i['Temp0'])+float(i['Temp1']))/2.0;
    if args.graphite:
        records.append(('{}.temp'.format(sectprefix),(now,int(i['Temp']))))
        records.append(('{}.temp0'.format(sectprefix),(now,int(i['Temp0']))))
        records.append(('{}.temp1'.format(sectprefix),(now,int(i['Temp1']))))
    else:
        print("{:7}: {:>10s}  {:.1f}°C".format("","Temp",temp))

if args.graphite:
    if args.graphite == "-":
        pprint(records)
    else:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((hostspec,port))
        sentbytes=0
        payload = pickle.dumps(records,protocol=2)
        message = struct.pack("!L", len(payload)) + payload
        while sentbytes < len(message):
            cnt = s.send(message[sentbytes:])
            if (cnt == 0):
                raise RuntimeError("socket connection broken")
            sentbytes = sentbytes + cnt
        s.close()
        print("{}-byte message ({} bytes payload) sent to graphite server.".format(len(message),len(payload)))
