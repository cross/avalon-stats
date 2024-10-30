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
from datetime import datetime,timedelta
import requests
import xml.etree.ElementTree as ET

from pprint import pprint

class SynaccessPDU(requests.Session):
    """Subclass requests.Session to hold on to our base URL.  We
    will use it for every request."""

    def __init__(self, base_url, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.base_url = base_url
        # Terminate with '/' once, so we can avoid it when assembling URLs
        if self.base_url[-1] != '/':
            self.base_url += '/'

    def request(self, method, url, **kwargs):
        if url[0] == '/':
            url = url[1:]

        full_url = self.base_url + url
        return super().request(method, full_url, **kwargs)


def status_xml(text):
    """Given the XML blob retrieved from a call to the "status.xml" document,
    parse out the values we're interesed in and return them."""
    try:
        root=ET.fromstring(text)
    except Exception as e:
        print("Failed to parse XML text ({} bytes): {}".format(len(text),e))
        return None

    # Return a dict with given keys
    retval = {
            'outlet_state': {},
            'temp': 0,
    }

    # expect up to 8 outlets
    #for child in root:
    #    pprint(child)
    for i in range(0,8):
        key=f"rly{i}"
        e = root.find(key)
        if e is not None:
            retval['outlet_state'][i] = bool(int(e.text))
        # TODO: temp

    #    else:
    #        print("no element found for {}".format(key))
    #pprint(root.find('rly0').text)

    return retval

def get_status(sess):
    """Issue request and decode the status response from the API.
    sess argument is a requests.Session object that has been configured."""
    r = sess.get('cmd.cgi', params='$A5')
    if (r.status_code / 100) != 2:
        print(f"Error.  Failed to retrieve status, HTTP status code {r.status_code}")
    #pprint(r.text)
    resp = r.text.strip().split(',')
    #pprint(resp)
    if resp[0] == '$A0':
        retval = {
                'outlet_state': {},
                'current': 0.0,
                'temp': 0.0,
        }
        states = resp[1]
        # This is a series of 0/1 bytes in reverse outlet order
        # list[::-1] walks the whole list backwards
        #pprint(list(states)[::-1])
        #pprint(dict(enumerate(list(states)[::-1])))
        #retval['outlet_state'] =  { i: bool(v) for i,v in dict(enumerate(list(states)[::-1], 1)) }
        for i,v in enumerate(list(states)[::-1]):
            retval['outlet_state'][i] = bool(v)

        retval['current'] = float(resp[2])
        # Docs say there can be one or two current-draw numbers.  My unit has
        # only one, but support the other.
        if len(resp) == 5:
            retval['current2']=float(resp[3])
            retval['temp']=float(resp[4])
        else:
            retval['temp']=float(resp[3])

        return retval
    else:
        print("Error.  Failed to retrieve status, API returned {} ({})".format(resp.text, str(resp)))

    return None




# Synaccess API commands.  No docs, I just sucked these out of their Web UI.
synaccess_commands = {
        'group_on': { 'grp': 0 },
        'group_off': { 'grp': 30 },
        'group_reboot': { 'rbg': 0 },
}

def gen_url(server,port=80):
    proto='http'
    if port == 443:
        proto="https"
    url = proto + '://' + server
    if port:
        url = url + ':' + str(port)
    url += '/'
    return url

#
# Program options
#
parser = argparse.ArgumentParser(description='Issue commands to a Synaccess PDU')
parser.add_argument('-s','--server','--host', default='127.0.0.1', help='API server name/address (host or host:port)')
parser.add_argument('-p','--port', type=int, default=80, help='API server port')
group = parser.add_mutually_exclusive_group()
group.add_argument('--status', action='store_true', help='show outlet status')
group.add_argument('-m','--monitor', action='store_true', help='Begin monitoring mode (does not exit)')
group.add_argument('--on', action='store_true', help='Turn the outlet group on')
group.add_argument('--off', action='store_true', help='Turn the outlet group off')
# TODO: Maybe --status should be allowed with the others?  No harm in printing
# status before taking reuqested action...
args = parser.parse_args()

# Build base API URL, and setup session object
apiurl = gen_url(args.server, args.port)
pdu = SynaccessPDU(apiurl)
pdu.auth=('admin','admin')

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

    sys.exit(0)

if args.on or args.off:
    print("This opertation is not yet supported.  Try something else.")
    sys.exit(1)

if args.monitor:
    timefmt="%Y-%m-%d %T"
    # TODO: Make period adjustable
    delay = 10
    call_time=time.time()
    while True:
        data = get_status(pdu)
        print("[{}] Outlets: {}  Temp: {}°C  Current: {}A".format(
            datetime.now().strftime(timefmt),
            " ".join(["On" if x else "Off" for x in data['outlet_state'].items()]),
            data['temp'],
            data['current']))
        try:
            call_time = call_time + delay
            time.sleep(call_time - time.time())
        except KeyboardInterrupt:
            print() # drop to new line after a ^C
            break


sys.exit(0)

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
    records = [ ('{}.elapsed'.format(sectprefix),(now,int(respdata['Elapsed']))),
                ('{}.accepted'.format(sectprefix),(now,int(respdata['Accepted']))),
                ('{}.rejected'.format(sectprefix),(now,int(respdata['Rejected']))),
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

# TODO: Print pool/work information?

sys.exit(0);

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
