#!/usr/bin/env python
#
# Copyright (c) 2010 Novell, Inc.
# All Rights Reserved.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of version 2 of the GNU General Public License as
# published by the Free Software Foundation.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.   See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, contact Novell, Inc.
#
# To contact Novell about this file by physical or electronic mail,
# you may find current contact information at www.novell.com
#
# ZYpp URL resolver plugin for Spacewalk-like servers
# Author: Duncan Mac-Vicar P. <dmacvicar@suse.de>
#
import sys
import os
import re
import logging
import traceback
sys.path.append("/usr/share/rhn/")
from up2date_client import rhnChannel
from up2date_client import up2dateAuth
from up2date_client import up2dateErrors

# for testing add the relative path to the load path
if "spacewalk-resolver.py" in sys.argv[0]:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../python'))

from zypp_plugin import Plugin

class SpacewalkResolverPlugin(Plugin):

    """ Pure exception handling """
    def RESOLVEURL(self, headers, body):
	try:
	    self.doRESOLVEURL(headers, body)
	except up2dateErrors.Error, e:
            self.answer("ERROR", {}, str(e))
	except:
            self.answer("ERROR", {}, traceback.format_exc())

    """ RESOLVEURL action """
    def doRESOLVEURL(self, headers, body):

        spacewalk_auth_headers = ['X-RHN-Server-Id',
                                  'X-RHN-Auth-User-Id',
                                  'X-RHN-Auth',
                                  'X-RHN-Auth-Server-Time',
                                  'X-RHN-Auth-Expire-Offset']

        if not os.geteuid() == 0:
            # you can't access auth data if you are not root
            self.answer("ERROR", {}, "Can't access managed repositores without root access")
            return


        if not headers.has_key('channel'):
            self.answer("ERROR", {}, "Missing argument channel")
            return

	details = rhnChannel.getChannelDetails();

	self.channel = None
        for channel in details:
            if channel['label'] == headers['channel']:
                self.channel = channel
        if not self.channel:
            self.answer("ERROR", {}, "Can't retrieve information for channel %s" % headers['channel'])
            return

        self.auth_headers = {}
	login_info = up2dateAuth.getLoginInfo()
	for k,v in login_info.items():
	    if k in spacewalk_auth_headers:
		self.auth_headers[k] = v
	#self.answer("META", li)

	# url might be a list type, we use the 1st one
	if type(self.channel['url']) == type([]):
	    self.channel['url'] = self.channel['url'][0]
        url = "%s/GET-REQ/%s?head_requests=no" % (self.channel['url'], self.channel['label'])

        self.answer("RESOLVEDURL", self.auth_headers, url)


plugin = SpacewalkResolverPlugin()
plugin.main()

