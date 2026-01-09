#!/usr/bin/python3
# vim:set et ts=4 sts=4 sw=4:
#
# This code will contact the API port of a cgminer application and
# report information.  This cgminer can be on any system, backed by
# CPU, GPU, or ASIC.  It's just an interface to cgminer.
#
# Chris Ross - © 2024

import socket
import argparse
import re
from collections import OrderedDict
import time
import struct
import pickle
from datetime import datetime,timedelta
from pprint import pprint

from requests import TooManyRedirects
from MinerAPI import MinerAPI, CGMiner, MinerException, BOSminer
from SynaccessPDU import SynaccessPDU

def restructure_stats0(data):
    """Given the first of the pair of dicts that 'stats' returns, restructure
    the inner 'MM IDn' elements to hashes, since that's what they should be
    but for some reason aren't."""
    if 'MM Count' not in data:
        raise RuntimeError("Expected to find 'MM Count' in stats response, but didn't.")
    mmcnt = data['MM Count']
    datapat = re.compile(r'(\w+)\[([^\]]*)\]')
    data['MM'] = list()
    for i in range(1,mmcnt+1):
        key = "MM ID{:d}".format(i)
        try:
            # How can we ever _not_ have this key if MM Count was available?
            dataset = data[key]
        except KeyError:
            print("KeyError looking for data['{}']?!?  data is: {}".format(key,data))
            raise
#        print("Processing dataset {} ({}): {}".format(i,key,dataset))
        result = OrderedDict()
        for m in re.finditer(datapat, dataset):
            result[m.group(1)] = m.group(2)
        data['MM'].append(result)
    return data
    

parser = argparse.ArgumentParser(description='Retrieve periodic status from cgminer.')
parser.add_argument('-s','--server','--host', default='127.0.0.1', help='API server name/address')
parser.add_argument('-p','--port', type=int, help='API server port')
parser.add_argument('-g','--graphite', metavar='SERVER', help='Format data for graphite, server:host or "-" for stdout')
parser.add_argument('-i','--cycletime', type=int, help='API server name/address')
parser.add_argument('--brief', action='store_true', help='Brief output mode')
parser.add_argument('--synaccess-api', help='URI to the API for a Synaccess PDU')
args = parser.parse_args()

# TODO: Should make an argparser for this
if args.graphite:
    # Parse the argument, which is expected to be a host:port specification
    # (but, other things also allowed for unusual run modes)
    if args.graphite == "-":
        hostspec = None
        port = None
        print("Should output graphite data to stdout")
    else:
        (hostspec,port) = MinerAPI.parse_host(args.graphite)
        print("Got host spec {}, port {}, for graphite server".format(hostspec,port))
        # TODO: Should verify ability to connect here, before polling cgminer

# Main program functionality, which is often called in a loop

def perform_cycle(graphite,host=None,port=None):
    """This is the main functionality of this program, or a single run of such.
    This is a function so it can be called repeatedly."""
    global high_fan_time
    global last_accepted_info

    # Open a new connection (cgminer only gives one answer per connection)
    # We'll detect the miner type and potentially recreate the connection with the right subclass
    miner = CGMiner(args.server,args.port)
    miner.open()

    # Icky that we're messing with variables in our callers scope...
    if high_fan_time:
        print("high_fan_time is: {}".format(high_fan_time.strftime("%H:%M:%S")),end='')
        if last_accepted_info['when']:
            print("; last_accepted time is {}".format(last_accepted_info['when'].strftime("%H:%M:%S")))
        else:
            print()

    # Get all of the data back from cgminer API
    response = miner.api_command(['summary', 'stats'])
    now = int(time.time())
    #pprint(response)
    # Different miners will return different things in different places.  We
    # need to be able to choose between them, and atm it seems that
    # STATUS['Msg'] is a string that identifies the miner.
    # BOSminer differences are now handled in the BOSminer subclass of CGMiner.
    try:
        miner_stats_msg=response['stats'][0]['STATUS'][0]['Msg']
    except KeyError as e:
        print(f"KeyError looking for response['stats'][0]['STATUS'][0]['Msg']: {e}")
        miner_stats_msg = None

    # Retry logic for getting summary data with MinerException handling
    max_retries = 5
    retry_delay_short = 3   # seconds for RETRY_SHORT
    retry_delay_long = 20   # seconds for RETRY_LONG

    for attempt in range(max_retries):
        try:
            respdata, _ = miner.handle_response(response['summary'][0],"summary") # Will exit on failure, return summary dict on success
            break  # Success, exit retry loop
        except MinerException as e:
            if not e.is_retryable():
                # Fatal error or warning, don't retry
                print(f"Non-retryable MinerException getting summary: {e}")
                raise

            if attempt < max_retries - 1:
                # Determine delay based on error type
                if e.error_type == MinerException.RETRY_SHORT:
                    delay = retry_delay_short
                elif e.error_type == MinerException.RETRY_LONG:
                    delay = retry_delay_long
                else:
                    delay = retry_delay_short  # Default fallback

                print(f"MinerException getting summary on attempt {attempt + 1}: {e}. Retrying in {delay} seconds...")
                time.sleep(delay)
                miner.close()
                miner.open()  # Reopen connection for retry
                response = miner.api_command(['summary', 'stats'])  # Re-fetch all data
                # Re-extract miner_stats_msg after re-fetching
                try:
                    miner_stats_msg=response['stats'][0]['STATUS'][0]['Msg']
                except KeyError as e:
                    print(f"KeyError looking for response['stats'][0]['STATUS'][0]['Msg']: {e}")
                    miner_stats_msg = None
            else:
                print(f"MinerException getting summary after {max_retries} attempts: {e}. Giving up.")
                raise

    if graphite:
        prefix = 'collectd.crosstest'
        sectprefix = prefix + '.summary'
        records = [ ('{}.elapsed'.format(sectprefix),(now,int(respdata['Elapsed']))),
                    ('{}.accepted'.format(sectprefix),(now,int(respdata['Accepted']))),
                    ('{}.rejected'.format(sectprefix),(now,int(respdata['Rejected']))),
                  ]
        for k,v in [(x,respdata[x]) for x in respdata.keys() if x[0:3] == "MHS"]:
            records.append(('{}.{}'.format(sectprefix,".".join(k.split())).lower(),(now,int(v))))
    else:
        #pprint(respdata)
        avmhs = float(respdata['MHS av'])
        if avmhs > 2000000:
            avspeed = ("TH/s", avmhs/1024.0/1024.0)
        elif avmhs > 1100:
            avspeed = ("GH/s", avmhs/1024.0)
        else:
            avspeed = ("MH/s", avmhs)
        if args.brief:
            # TODO: Scale the :7.2f format differently based on the above logic
            print("Elapsed {} {:7.2f}{:4s} av A{} R{}".format(timedelta(seconds=respdata['Elapsed']), avspeed[1], avspeed[0], respdata['Accepted'], respdata['Rejected']), end='')
        else:
            print("Summary:")
            print("  Running for: {}".format(timedelta(seconds=respdata['Elapsed'])))
            print("  {:4s} av    : {:7.2f}".format(avspeed[0], avspeed[1]))
            print("  Accepted   : {:7d}".format(respdata['Accepted']))
            print("  Rejected   : {:7d}".format(respdata['Rejected']))

    # Keep track of whether we're seeing accepts, or whether we've gone idle.
#    pprint(last_accepted_info)
    if 'count' not in last_accepted_info or last_accepted_info['count'] == None:
        last_accepted_info['count'] = respdata['Accepted']
        if respdata['Accepted'] > 0:
            last_accepted_info['when'] = datetime.now()
        else:
            last_accepted_info['when'] = None
    if respdata['Accepted'] > last_accepted_info['count']:
#        if high_fan_time:
#            print(f"Updating last_accepted_info since count is now {respdata['Accepted']}")
        last_accepted_info['count'] = respdata['Accepted']
        last_accepted_info['when'] = datetime.now()
    elif respdata['Accepted'] < last_accepted_info['count']:
        # I wonder if this ever happens except for restart, when it resets to
        # zero?  That is a slightly more normal condition, are others possible?
        if respdata['Accepted'] == 0:
            print(f"Accepted count has zero'd, probable resstart.  Resetting.")
            last_accepted_info['when'] = None
        else:
            print(f"Accepted count dropped?  Response of {respdata['Accepted']} is less than {last_accepted_info['count']} (set at {last_accepted_info['when'].strftime('%H:%M:%S')})")
            # TODO: Should I leave this set to a time when not zero?
            last_accepted_info['when'] = None
        last_accepted_info['count'] = respdata['Accepted']
    else:
        if high_fan_time and last_accepted_info['when'] and (datetime.now() - last_accepted_info['when']) > timedelta(minutes=2):
            print(f"* {respdata['Accepted']} is not > {last_accepted_info['count']}")
#    pprint(last_accepted_info)

    # TODO: Print pool/work information?

    # cgminer on the Avalon 6, our original implemetation case, returns two
    # (or more?) hashes for stats.  BOSminer in BraiinsOS claims it will
    # return stats regarding getwork times for any device or pool that has
    # 1 or more getworks.  But, in initial testing, it seems to return only
    # zero values, even while doing useful work.  Bears investigation.

    # Handle BOSminer (Braiins OS) miners
    if miner_stats_msg and miner_stats_msg.startswith("BOS"):
        miner.close()
        # Recreate connection with BOSminer subclass
        miner = BOSminer(args.server, args.port)
        miner.open()

        # Get device info using BOSminer's method (includes retry logic)
        device_info = miner.get_device_info()

        # Format and display the stats
        output_lines = miner.format_device_stats(
            device_info['devs_data'],
            device_info['temps_data'],
            device_info['fans_data'],
            brief=args.brief
        )

        for line in output_lines:
            print(line, end="")

        if args.brief:
            # Terminate the continuing line above
            print(flush=True)
        return
    else:
        #print(f"Miner stats message was {miner_stats_msg}, so continuing to process data from the originalresponse.")
        pass
    # TODO: And, we should run the rest of the code below to track data across
    # runs.  But while we cope with the different data structure, just do this
    # and return for now.

    # Break-out and report per-device stats
    respdata, _ = miner.handle_response(response['stats'][0],"stats") # Will exit on failure, return stats list on success
    #pprint(respdata)

    try:
        (stats0,stats1) = respdata
        stats0 = restructure_stats0(stats0)
        #pprint(stats0)
    except ValueError as e:
        print("ValueError parsing response, did respdata not have two values?")
        print(f"  respdata: {respdata}")
        exit(7)

    if not graphite and not args.brief and stats0['MM']:
        print("Device stats:")
    #else:
    #    records = []

    for i in stats0['MM']:
        temp = (float(i['Temp0'])+float(i['Temp1']))/2.0;
        if graphite:
            sectprefix = prefix + '.stats.mm.{}'.format(i['DNA'])
            records.append(('{}.fan'.format(sectprefix),(now,int(i['Fan']))))
            records.append(('{}.ghsmm'.format(sectprefix),(now,float(i['GHSmm']))))
            records.append(('{}.ghs5m'.format(sectprefix),(now,float(i['GHS5m']))))
        else:
            if args.brief:
                print(" ; MM {:4s}: {}/{} {}rpm {:.1f}°C".format(i['DNA'][-4:],i['GHSmm'],i['GHS5m'],i['Fan'],temp), end="")
            else:
                print("MM {:4s}: {:>10s}  {}/{}".format(i['DNA'][-4:],"Ghz (?/5m)",i['GHSmm'],i['GHS5m']))
                print("{:7}: {:>10s}  {}rpm".format("","Fan",i['Fan']))
        if int(i['Fan']) > 6800 and not high_fan_time:
            high_fan_time=datetime.now()
        # XXX - This will break if one of the units has a high fan and another
        # doesn't.  Need to fix this if we're ever running against a cgminer
        # with more than one computation unit on it....
        if high_fan_time and int(i['Fan']) < 6200:
            high_fan_time=None

        # I'm not sure what 'Temp' 'Temp0' and 'Temp1' each are, but 'Temp' looks
        # to be much lower, so maybe enclosure?  I'm going to average 'Temp0' and
        # 'Temp1' to be the number I think I'm looking for, but that's just a
        # random guess.
        if graphite:
            records.append(('{}.temp'.format(sectprefix),(now,int(i['Temp']))))
            records.append(('{}.temp0'.format(sectprefix),(now,int(i['Temp0']))))
            records.append(('{}.temp1'.format(sectprefix),(now,int(i['Temp1']))))
        elif not args.brief:
            print("{:7}: {:>10s}  {:.1f}°C".format("","Temp",temp))

    if graphite:
        if graphite == "-":
            pprint(records)
        else:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((host,port))
            sentbytes=0
            payload = pickle.dumps(records,protocol=2)
            message = struct.pack("!L", len(payload)) + payload
            while sentbytes < len(message):
                cnt = s.send(message[sentbytes:])
                if (cnt == 0):
                    raise RuntimeError("socket connection broken")
                sentbytes = sentbytes + cnt
            s.close()
#            print("{}-byte message ({} bytes payload) sent to graphite server".format(len(message),len(payload)),end="")
            print("{}-byte message sent to graphite server".format(len(message)),end="")
            if args.cycletime:
                print(" at {}.".format(time.strftime("%d-%b-%Y %T")))
            else:
                print(".")
    elif args.brief:
        # terminate the contiinuing line above
        print(flush=True)
    # Close the MinerAPI (will be reopened next call)
    miner.close()

#
# Main
#

high_fan_time=None
last_accepted_info={'count': None, 'when': None}
if args.cycletime:
    while True:
        now = time.time()
        ntime = now - (now % args.cycletime) + args.cycletime
        # Don't repeat too quickly, which can happen on the first run
        if ((ntime-now) < (args.cycletime // 3)):
            ntime += args.cycletime
        try:
            if args.graphite:
                perform_cycle(args.graphite, hostspec, port)
            else:
                perform_cycle(False)
        except (ConnectionError,OSError) as e:
            if isinstance(e,ConnectionError):
                print("** Connection error at {} ({}), will try again next cycle.".format(time.strftime("%d-%b-%Y %T"),e))
            else:
                print("** OSError ({}) at {}, will try again next cycle.".format(e,time.strftime("%d-%b-%Y %T")))
            print(end='',flush=True)
        try:
            now = time.time()
            if now < ntime:
    #            print("Sleeping {:0.3f}".format(ntime-now))
                time.sleep(ntime - now)
            else:
                # If we took too long, increment to the next start cycle time
                while now > ntime:
                    ntime += args.cycletime
        except KeyboardInterrupt as e:
            print("Exiting...")
            exit(1)

        if high_fan_time and (datetime.now() - high_fan_time) > timedelta(seconds=360):
            if ( datetime.now().hour < 7 or datetime.now().hour >= 19 ) and \
               last_accepted_info and last_accepted_info['when'] and \
               ( datetime.now() - last_accepted_info['when'] ) < timedelta(seconds=120):
                print("The fan is above normal levels, but we're still submitting accepted results and are outside of normal business hours.")
            else:
                if args.synaccess_api:
                    try:
                        print("Issuing a power-down to the PDU ... ", end='')
                        pdu=SynaccessPDU(args.synaccess_api)
                        # TODO fail if fail.  Will need to call a method to see if it works.  ping?  status?
                        if pdu.group_power(False):
                            high_fan_time=None
                            last_accepted_info={'count': None, 'when': None}
                            print("successful.")
                            # Sleep for a bit, so the next query won't get irrelevant info
                            time.sleep(2)
                        else:
                            print("failed. (I should get back a \"why\" to pass on, but don't now)")
                    except Exception as e:
                        print(f"Failed to connect to or issue power-down to the PDU: {e}")
                else:
                    print("** I want to shut down the PDU now; but I don't know how to contact it.")
else:
    if args.graphite:
        perform_cycle(args.graphite, hostspec, port)
    else:
        perform_cycle(False)
