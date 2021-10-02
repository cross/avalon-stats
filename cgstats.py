#!/usr/bin/python3
# vim:set et ts=4 sts=4 sw=4:
#

import socket
import json
import sys
import argparse
import re
from collections import OrderedDict
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

response = api_get_summary()
respdata = handle_response(response,"summary") # Will exit on failure, return summary dict on success

if args.graphite:
    print("TODO:  Should be outputting graphite data, but don't know how to yet!")

#pprint(respdata)
print("Summary:")
print("  Running for: {}".format(timedelta(seconds=respdata['Elapsed'])))
print("  GHS av     : {:7.2f}".format(respdata['MHS av']/1024.0))
print("  Accepted   : {:7d}".format(respdata['Accepted']))
print("  Rejected   : {:7d}".format(respdata['Rejected']))

# TODO: Print pool/work information?

# Print per-device stats
response = api_get_stats()
respdata = handle_response(response,"stats") # Will exit on failure, return stats list on success
#pprint(respdata)

(stats0,stats1) = response['STATS']

stats0 = restructure_stats0(stats0)
#pprint(stats0)
print("Device stats:")
for i in stats0['MM']:
    print("MM {:4s}: {:>10s}  {}/{}".format(i['DNA'][-4:],"Ghz (?/5m)",i['GHSmm'],i['GHS5m']))
    print("{:7}: {:>10s}  {}rpm".format("","Fan",i['Fan']))
    # I'm not sure what 'Temp' 'Temp0' and 'Temp1' each are, but 'Temp' looks
    # to be much lower, so maybe enclosure?  I'm going to average 'Temp0' and
    # 'Temp1' to be the number I think I'm looking for, but that's just a
    # random guess.
    temp = (float(i['Temp0'])+float(i['Temp1']))/2.0;
    print("{:7}: {:>10s}  {:.1f}°C".format("","Temp",temp))
#elif 'STATUS' in response:


