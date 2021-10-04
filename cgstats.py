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

def getresponse(socket):
    buffer = socket.recv(4096).decode()
    done = False
    while not done:
        more = socket.recv(4096).decode()
        if not more:
            done = True
        else:
            buffer = buffer+more
    if buffer:
        if buffer[-1] == "\x00":
            buffer = buffer[:-1]
        return buffer

def _api_command(command,param,server,port):
    s = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    s.connect((server,port))
    if param:
        s.send(json.dumps({"command":command,"parameter":param}).encode())
    else:
        s.send(json.dumps({"command":command}).encode())

    response = json.loads(getresponse(s))
    s.close()
    # Check that the response was structed as we expect.
    if 'STATUS' not in response:
        print("Unrecognized response, no STATUS")
        sys.exit(2)

    return response

def handle_response(data,command):
    """Handle the response to an API request.  If the repsponse indicates
    other than successful, report and exit.  Otherwise, return the relevant
    portion of the data, if we recognize it, based on "Code" in response."""
    status=data['STATUS'][0]
    # TODO: expect 'S' or 'E', should I deal with others?
    #   STATUS=X Where X is one of:
    #     W - Warning
    #     I - Informational
    #     S - Success
    #     E - Error
    #     F - Fatal (code bug)
    if status['STATUS'] == "E":
        print("Failed to execute command {}: {}".format(api_command[0],status['Msg']))
        sys.exit(3)
    if status['STATUS'] != "S":
        print("Unexpected status '{}': {}".format(status['STATUS'],status['Msg']))
        sys.exit(4)

    if status['Code'] == 70:    # MSG_MINESTATS:
        return data['STATS']
    elif status['Code'] == 11:  # MSG_SUMM
        return data['SUMMARY'][0]
    else:
        print("WARNING: Don't recognize response with code {}, returning whole response data.".format(status['Code']))
        return data

def restructure_stats0(data):
    """Given the first of the pair of dicts that 'stats' returns, restrucure
    the inner 'MM IDn' elements to hashes, since that's what they should be
    but for some reason aren't."""
    if 'MM Count' not in data:
        raise RuntimeException("Expected to find 'MM Count' in stats response, but didn't.")
    mmcnt = data['MM Count']
    datapat = re.compile(r'(\w+)\[([^\]]*)\]')
    data['MM'] = list()
    for i in range(1,mmcnt+1):
        key = "MM ID{:d}".format(i)
        dataset = data[key]
#        print("Processing dataset {} ({}): {}".format(i,key,dataset))
        result = OrderedDict()
        for m in re.finditer(datapat, dataset):
            result[m.group(1)] = m.group(2)
        data['MM'].append(result)
    return data
    

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


response = api_get_summary()
now = int(time.time())
respdata = handle_response(response,"summary") # Will exit on failure, return summary dict on success
#pprint(respdata)

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

# Print per-device stats
response = api_get_stats()
now = int(time.time())
respdata = handle_response(response,"stats") # Will exit on failure, return stats list on success
#pprint(respdata)

(stats0,stats1) = response['STATS']
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
