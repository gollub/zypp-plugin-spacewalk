#!/usr/bin/env python
#
# Copyright (c) 2010 Novell, Inc.
# All Rights Reserved.
#
# Based on yum-rhn-plugin
# Copyright (c) 1999-2010 Red Hat, Inc.
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
import os
import sys
import time

sys.path.append("/usr/share/rhn/")

from up2date_client import up2dateLog
from up2date_client import config
from up2date_client import rpmUtils
from up2date_client import rhnPackageInfo

import subprocess
import xml.dom.minidom

log = up2dateLog.initLog()

# file used to keep track of the next time rhn_check
# is allowed to update the package list on the server
LAST_UPDATE_FILE="/var/lib/up2date/dbtimestamp"

# mark this module as acceptable
__rhnexport__ = [
    'update',
    'remove',
    'refresh_list',
    'fullUpdate',
    'checkNeedUpdate',
    'runTransaction',
    'verify',
    'verifyAll'
]

def __package_name_from_tup__(tup):
    """ Create a zypper package tuple from an rhn package tuple.
    Choose from the above styles to be compatible with yum.parsePackage
                                                    """
    n, v, r, e, a = tup[:]
    pkginfo = n
    if e:
        v = '%s:%s' % (e, v)
    if v:
	pkginfo = '%s-%s' % (pkginfo, v)
    if r:
	pkginfo = '%s-%s' % (pkginfo, r)
    return pkginfo

class Zypper:
    def __init__(self):
        pass

    def __parse_output(self, output):
        log.log_me(output)
        dom = xml.dom.minidom.parseString(output)
        messages = dom.getElementsByTagName("message")
        for message in messages:
            yield message.firstChild.nodeValue

    def __execute(self, args):
        cmd = ["zypper"]
        cmd.extend(args)
        log.log_me("Executing: %s" % cmd)
        task = subprocess.Popen(' '.join(cmd), shell=True, stdout=subprocess.PIPE)
        stdout_text, stderr_text = task.communicate()
        errors = []
        for error in self.__parse_output(stdout_text):
            errors.append(error)
        return (task.returncode, "\n".join(errors), {})

    def install(self, package_list):
        args = ["-n", "-x", "install"]
        args.extend(package_list)
        return self.__execute(args)

    def remove(self, package_list):
        args = ["-n", "-x", "remove"]
        args.extend(package_list)
        return self.__execute(args)

    def update(self):
        args = ["-n", "-x", "update"]
        return self.__execute(args)

    def __transact_args__(self, transaction_data):
        """ Add packages to transaction.
            transaction_data is in format:
            { 'packages' : [
            [['name', '1.0.0', '1', '', ''], 'e'], ...
            # name,    versio, rel., epoch, arch,   flag
            ]}
            where flag can be:
                i - install
                u - update
                e - remove
                r - rollback
            Note: install and update will check for dependecies and
            obsoletes and will install them if needed.
            Rollback do not check anything and will assume that state
            to which we are rolling back should be correct.
        """
        args = ["-n", "-x", "install", "--"]

        for pkgtup, action in transaction_data['packages']:
            if ((action == "u") or (action == "i") or (action == "r")):
                args.append("+" + __package_name_from_tup__(pkgtup))
            elif action == 'e':
                args.append("-" + __package_name_from_tup__(pkgtup))
            else:
                assert False, "Unknown package transaction action."
        return args

    def patch_install(self, patch_list):
        args = ["-n", "-x", "install"]
        patches = ["patch:%s" % i for i in patch_list]
        args.extend(patches)
        response = self.__execute(args)
        if response[0] == 102:
            # zypper returns a status code as the first element of the
            # tuple. 102 is a status code that suggests a reboot. We
            # intercept that and return a 0 status which is the only
            # "successful" status
            message =  ("This system requires a reboot in order for the update "
                        "to take effect.\n") + response[1]
            response = (0, message, response[2])
        return response

    def transact(self, transaction_data):
        args = self.__transact_args__(transaction_data)
        return self.__execute(args)

def remove(package_list, cache_only=None):
    """We have been told that we should remove packages"""
    if cache_only:
        return (0, "no-ops for caching", {})

    if type(package_list) != type([]):
        return (13, "Invalid arguments passed to function", {})

    log.log_debug("Called remove_packages", package_list)

    log.log_debug("Called remove", package_list)
    zypper = Zypper()
    return zypper.remove([__package_name_from_tup__(x) for x in package_list])

def update(package_list, cache_only=None):
    """We have been told that we should retrieve/install packages"""
    if type(package_list) != type([]):
        return (13, "Invalid arguments passed to function", {})

    log.log_me("Called update", package_list)
    zypper = Zypper()
    return zypper.install([__package_name_from_tup__(x) for x in package_list])
def patch_install(patch_list):
    log.log_me("Called patch install", patch_list)

    zypper = Zypper()
    return zypper.patch_install(patch_list)

def runTransaction(transaction_data, cache_only=None):
    """ Run a transaction on a group of packages.
        This was historicaly meant as generic call, but
        is only called for rollback.
        Therefore we change all actions "i" (install) to
        "r" (rollback) where we will not check dependencies and obsoletes.
    """
    if cache_only:
        return (0, "no-ops for caching", {})
    log.log_me("Called run transaction")
    zypper = Zypper()
    return zypper.transact(transaction_data)

def fullUpdate(force=0, cache_only=None):
    """ Update all packages on the system. """
    zypper = Zypper()
    return zypper.update()

def checkNeedUpdate(rhnsd=None, cache_only=None):
    """ Check if the locally installed package list changed, if
        needed the list is updated on the server
        In case of error avoid pushing data to stay safe
    """
    if cache_only:
        return (0, "no-ops for caching", {})

    data = {}
    dbpath = "/var/lib/rpm"
    cfg = config.initUp2dateConfig()
    if cfg['dbpath']:
        dbpath = cfg['dbpath']
    RPM_PACKAGE_FILE="%s/Packages" % dbpath

    try:
        dbtime = os.stat(RPM_PACKAGE_FILE)[8] # 8 is st_mtime
    except:
        return (0, "unable to stat the rpm database", data)
    try:
        last = os.stat(LAST_UPDATE_FILE)[8]
    except:
        last = 0;

    # Never update the package list more than once every 1/2 hour
    if last >= (dbtime - 10):
        return (0, "rpm database not modified since last update (or package "
            "list recently updated)", data)

    if last == 0:
        try:
            file = open(LAST_UPDATE_FILE, "w+")
            file.close()
        except:
            return (0, "unable to open the timestamp file", data)

    # call the refresh_list action with a argument so we know it's
    # from rhnsd
    return refresh_list(rhnsd=1)

def refresh_list(rhnsd=None, cache_only=None):
    """ push again the list of rpm packages to the server """
    if cache_only:
        return (0, "no-ops for caching", {})
    log.log_debug("Called refresh_rpmlist")

    try:
        rhnPackageInfo.updatePackageProfile()
    except:
        print "ERROR: refreshing remote package list for System Profile"
        return (20, "Error refreshing package list", {})

    touch_time_stamp()
    return (0, "rpmlist refreshed", {})


def touch_time_stamp():
    try:
        file_d = open(LAST_UPDATE_FILE, "w+")
        file_d.close()
    except:
        return (0, "unable to open the timestamp file", {})
    # Never update the package list more than once every hour.
    t = time.time()
    try:
        os.utime(LAST_UPDATE_FILE, (t, t))

    except:
        return (0, "unable to set the time stamp on the time stamp file %s"
                % LAST_UPDATE_FILE, {})

def verify(packages, cache_only=None):
    log.log_debug("Called packages.verify")
    if cache_only:
        return (0, "no-ops for caching", {})

    data = {}
    data['name'] = "packages.verify"
    data['version'] = 0
    ret, missing_packages = rpmUtils.verifyPackages(packages)

    data['verify_info'] = ret

    if len(missing_packages):
        data['name'] = "packages.verify.missing_packages"
        data['version'] = 0
        data['missing_packages'] = missing_packages
        return(43, "packages requested to be verified are missing", data)

    return (0, "packages verified", data)

def verifyAll(cache_only=None):
    log.log_debug("Called packages.verifyAll")
    if cache_only:
        return (0, "no-ops for caching", {})

    data = {}
    data['name'] = "packages.verifyAll"
    data['version'] = 0

    ret = rpmUtils.verifyAllPackages()
    data['verify_info'] = ret
    return (0, "packages verified", data)

# just for testing
if __name__ == "__main__":
    #print update([['rubygem-thoughtbot-shoulda', '2.9.2', '1.1', '', 'x86_64']])
    #print remove([['ant', '1.7.1', '12.1', '', 'x86_64']])

    print "Transaction args:"
    transaction = { 'packages' : [
            [['foo', '1.0.0', '1', '', ''], 'e'],
            [ ['bar', '2.0.0', '2', '', ''], 'i'] ]}
    zypper = Zypper()
    print zypper.__transact_args__(transaction)


