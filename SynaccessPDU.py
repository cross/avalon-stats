#!/usr/bin/python3
# vim:set et ts=4 sts=4 sw=4:
#
# This class represents an API connection to a Synaccess netBooter switched
# [and metered] PDU.  It was written originally for use with a netBooter™
# NP-0201DU but is hoped to work with most/all netBooter™ B and DU series
# models.  It will need changes to work with the more modern Synaccess DX
# series or SynLink series PDUs.
#
# Chris Ross - © 2024

import requests
import xml.etree.ElementTree as ET

#from pprint import pprint

# Synaccess API commands.  No docs, I just sucked these out of their Web UI.
synaccess_commands = {
        'group_on': { 'grp': 0 },
        'group_off': { 'grp': 30 },
        'group_reboot': { 'rbg': 0 },
}

class SynaccessPDU(requests.Session):
    """Subclass requests.Session to hold on to our base URL.  We
    will use it for every request.
    This will consist of an active conncetion to the API on the device.
    """

    def __init__(self, base_url, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.base_url = base_url
        # Terminate with '/' once, so we can avoid it when assembling URLs
        if self.base_url[-1] != '/':
            self.base_url += '/'
        self.auth=('admin','admin')

    def request(self, method, url, **kwargs):
        if url[0] == '/':
            url = url[1:]

        full_url = self.base_url + url
        return super().request(method, full_url, **kwargs)

    def group_power(self, power_on, group=1):
        """Send a command to power up or down a group.  using a boolean
        arg to be "on or not", instead of some sort of "on"/"off" argument
        seems a little unpleasant, but it'll work.
        nb, I've only ever set this up to cope with the one group on a
        NP-0201DU.  The "group" parameter is really just a concept for now."""
        if power_on:
            p=synaccess_commands["group_on"]
        else:
            p=synaccess_commands["group_off"]

        r = self.get('cmd.cgi', params=p)
        if (r.status_code / 100) != 2:
            print(f"Error.  Failed to set group power, HTTP status code {r.status_code}")
            #pprint(r.text)
            return None
        resp = r.text.strip()
        #pprint(resp)
        if resp == '$A0':
            return True
        else:
            print("Error.  Failed to switch power group, API returned {} ({})".format(resp.text, str(resp)))
            return False


def status_xml(text):
    """Given the XML blob retrieved from a call to the "status.xml" document,
    parse out the values we're interested in and return them."""
    try:
        root=ET.fromstring(text)
    except Exception as e:
        print("Failed to parse XML text ({} bytes): {}".format(len(text),e))
        return None

    # Return a dict with given keys
    retval = {
            'outlet_state': {},
            'temp': 0.0,
            'current': 0.0,
    }

    # expect up to 8 outlets
    #for child in root:
    #    pprint(child.text)
    for i in range(0,8):
        key=f"rly{i}"
        e = root.find(key)
        if e is not None:
            retval['outlet_state'][i] = bool(int(e.text))
    # Temperature reading(s)
    e = root.find("tp0")
    if e is not None:
        retval['temp'] = float(e.text.split('/')[0])
    e = root.find("tp1")
    if e is not None:
        retval['temp_max'] = float(e.text.split('/')[0])
    e = root.find("tp2")
    if e is not None:
        retval['temp_min'] = float(e.text.split('/')[0])
    # There seem to be places for up to 8 current sensors.  We're just
    # using the first one for now. (ac0 .. ac8)
    e = root.find("ac0")
    if e is not None:
        # These sensors contain a string of "<now-current> - <max-current>"
        c1=[x.strip() for x in e.text.split("-")]
        try:
            retval['current'] = float(c1[0])
            retval['current_max'] = float(c1[1])
        except Exception as e:
            print("Failed to extract current values: {}".format(e))
            pass

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
        # nb: Be cautions here.  bool('0') is True if it's a string.
        retval['outlet_state'] = { i: bool(int(v)) for i,v in enumerate(list(states)[::-1]) }
#        for i,v in enumerate(list(states)[::-1]):
#            pprint([v, bool(v)])
#            retval['outlet_state'][i] = bool(v)

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
