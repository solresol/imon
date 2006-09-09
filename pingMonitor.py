#! /usr/bin/env python

# (c) Greg Baker (greg.baker@ifost.org.au)
# This software is licensed to anyone who wants to use it for any reason
# in any way.  If you want to let me know what you do with it,  even better.
# Needless to say,  it doesn't come with any warranty or support.  If it
# breaks,  you get to keep all the pieces.
#
# This program is designed to be run from cron,  and pings a list of
# computers.  If any of them are down,  it sends an email to the system
# admin,  unless it has sent one in the recent past.  It also alerts
# when a machine that was down comes back up again.
#
# $Log$
# Revision 1.1  2004/10/28 21:19:17  gregb
# Initial revision
#
#

rcs_version = "$Id: pingMonitor.py 23 2004-10-28 21:18:42Z gregb $"

import os
import time
import signal
import re
import string
import sys
import ConfigParser

# Where is the imon.conf file?
imonconf = '/etc/imon/imon.conf'

config = ConfigParser.ConfigParser

# what command should I execute to send a 1 packet ping?
# %s gets substituted for the thing to ping
if sys.platform == 'win32':
    pingCommand = 'ping -w 1000000 -n 1 %s'
else:
    uname = os.uname()[0]
    if uname == 'Linux':
        pingCommand = '/bin/ping -c 1 %s '
    elif uname == 'HP-UX':
        pingCommand = "/usr/sbin/ping %s -n 1 "
    elif uname == 'SunOS':
        pingCommand = "/usr/sbin/ping %s 1 "
    elif uname == 'OpenBSD':
        pingCommand = "/sbin/ping -c 1 %s "
    else:
        # you will need to fill this in,  it's probably wrong
        pingCommand = "/usr/sbin/ping -c 1 %s "


# what command should I run to send a mail message?  The
if uname == 'Linux':
    mailCommand = "/bin/mail -s '%(subject)s' %(recipient)s"
elif uname == 'HP-UX' or uname == 'SunOS':
    mailCommand = "/usr/bin/mailx -s '%(subject)s' %(recipient)s"
elif uname == 'OpenBSD':
    mailCommand = "/usr/bin/mail -s '%(subject)s' %(recipient)s"
else:
    mailCommand = "mail -s '%(subject)s' %(recipient)s"

######################################################################
##  That's about it for configuration options
######################################################################

storage_directory = os.path.dirname(deviceTrackingStore)
if not(os.path.exists(storage_directory)):
    try:
        os.makedirs(storage_directory)  # new in Python 1.5.2
    except AttributeError:
        # fallback could have problems,  doesn't catch exceptions at all
        ds = string.split(storage_directory)
        for i in range(2,len(ds)):
            directory = string.join(ds[:i],'/')
            if not(os.path.isdir(directory)):
                os.mkdir(directory) 
elif not(os.path.isdir(storage_directory)):
    dict = {'subject' : 'Ping Monitor configuration problem',
            'recipient' : emailTo }
    email = os.popen(mailCommand%dict,'w')
    email.write('I have been configured to store device tracking\n')
    email.write('information in files of the following form:\n\n')
    email.write('   '+deviceTrackingStore)
    email.write('\n\nThis means that I need to have a directory called\n\n')
    email.write('   '+storage_directory)
    email.write('\n\nUnfortunately,  it already exists,  and is _not_ a\n')
    email.write('directory.  I cannot continue.\n')
    email.write('\nPlease accept my apologies if you have received\n')
    email.write('many copies of this message.\n')
    email.close()

# a hash of pids to pingableDevice objects
pidToPingableDevice = {}

def sigchildHandler(*args):
    global pidToPingableDevice
    global spawning_being_performed
    try:
        (pid,status) = os.wait()
    except:
        signal.signal(signal.SIGCHLD,sigchildHandler)
        return
    if pidToPingableDevice.has_key(pid):
        pidToPingableDevice[pid].ping_success_callback()
    elif spawning_being_performed is not None:
        pidToPingableDevice[pid] = spawning_being_performed
        spawning_being_performed.ping_success_callback()
    else:
        pass
    signal.signal(signal.SIGCHLD,sigchildHandler)


def reap():
    global pidToPingableDevice
    for process in pidToPingableDevice.values():
        if process.ping_process_id is not None:
            process.ping_failure_callback()
        #os.kill(process,signal.SIGTERM)

def notify(device,message):
    dict = {'subject' : 'Ping Monitor event on ' + device,
            'recipient' : emailTo }
    email = os.popen(mailCommand%dict,'w')
    email.write('At ')
    email.write(time.asctime(time.localtime(time.time())))
    email.write(' I noted the following fact:\n ')
    email.write(device+" "+message)
    email.close()


file_format_error = 'FileFormatError'
class PingableDevice:
    def __init__(self,devicename):
        self.devicename = devicename
        # ping_process_id is set when the fork is performed, and reset
        # when a suc
        self.ping_process_id = None
        self.callback_block = None
        # These aren't necessarily correct,  they will get overridden
        # by get_previous_status
        self.is_up = 1
        self.no_response_count = 0
        self.number_of_downs  = 0
        self.last_up_time = time.time()
        self.last_rereminder = 0.0
        # 
        self.get_previous_status()
    def get_previous_status(self):
        self.was_up = 1
        self.number_of_downs = 0
        try:
            try:
                self.f = open(deviceTrackingStore % self.devicename,'r')
            except:
                raise file_format_error
            # The file format should look like one of these
            version = self.get_value_from_file('FileFormatVersion')
            last_up_time = self.get_value_from_file('LastUpTime')
            self.last_up_time = string.atof(last_up_time)
            status = self.get_value_from_file('Status')
            if status not in [noResponseStatus,okResponseStatus]:
                raise file_format_error
            if status == noResponseStatus:
                self.was_up = 0
                count = self.get_value_from_file('NoResponseCount')
                self.no_response_count = string.atoi(count)
                last_rereminder = self.get_value_from_file('LastRereminder')
                self.last_rereminder = string.atof(last_rereminder)
            self.f.close()
        except file_format_error:
            self.was_up = 1
            self.number_of_downs = 0
            self.last_up_time = time.time()
            return
    def write_status_file(self):
        self.f = open(deviceTrackingStore % self.devicename,'w')
        self.f.write('FileFormatVersion=1\n')
        if self.is_up:
            t = time.time()
            s = time.asctime(time.localtime(t))
            self.f.write('LastUpTime='+`t`+'\n')
            self.f.write('Status='+okResponseStatus+'\n')
            self.f.write('HumanReadableLastUpTime='+s+'\n')
        else:
            self.f.write('LastUpTime='+`self.last_up_time`+'\n')
            self.f.write('Status='+noResponseStatus+'\n')
            self.f.write('NoResponseCount='+`self.no_response_count`+'\n')
            self.f.write('LastRereminder='+`self.last_rereminder`+'\n')
            s = time.asctime(time.localtime(self.last_up_time))
            self.f.write('HumanReadableLastUpTime='+s+'\n')
        self.f.close()
    def get_value_from_file(self,name):
        line = self.f.readline()
        [left,right]=string.split(string.strip(line),'=',1)
        if left != name: raise file_format_error
        return right
    def ping_success_callback(self):
        # we can end up here in one of two ways...
        #  1. ping completed,  and we are being called back as a result
        #  2. ping was terminated by the failure_callback below
        # either way,  we need to reset the ping_process_id to nothing
        self.ping_process_id = None
        if self.callback_block is not None:  return
        if not(self.was_up) and self.last_rereminder != 0.0:
                notify(self.devicename,'is alive again')
        self.is_up = 1
        self.write_status_file()
    def ping_failure_callback(self):
        self.callback_block = 1
        sys.stderr.write(self.devicename + ' down\n')
        # this will call sigchildHandler to be called,  which is why
        # we just blocked the callback_block
        try:
            os.kill(self.ping_process_id,signal.SIGTERM)
        except os.error:
            # don't know if this is the correct thing to do here
            self.callback_block = None
            self.ping_success_callback()
            return
        self.ping_process_id = None
        self.no_response_count = self.no_response_count + 1
        self.is_up = 0
        if self.no_response_count >= numberOfPingFailuresBeforeNotification:
            now = time.time()
            last_up_time = time.asctime(time.localtime(self.last_up_time))
            if self.last_rereminder == 0.0:
                # then we've never alerted anyone before
                notify(self.devicename,'has not responded since '+last_up_time)
                self.last_rereminder = now
            elif (now - self.last_rereminder) > reminderInterval:
                notify(self.devicename,
                       'is still down -- no response since '+last_up_time)
                self.last_rereminder = now
            else:
                # already been notified,  no need to say again.
                pass
        self.write_status_file()
    def spawn_ping(self):
        self.callback_block = None
        pid = os.fork()
        global pidToPingableDevice
        global pingCommand
        global pingPause
        global spawning_being_performed
        spawning_being_performed = self
        cmd = (pingCommand % self.devicename) + ">/dev/null"
        if pid == 0:
            os.system(cmd)
            sys.exit()
        else:
            self.ping_process_id = pid
            try:
                time.sleep(pingPause)
            except:
                # got a response pretty quickly obviously!
                pass
            return pid


importantDevicesFile = open(importantDevices,'r')
devices = []
for device in importantDevicesFile.readlines():
    if re.match('^\s*[#;]',device): continue
    if re.match('^\s*$',device): continue
    devices.append(PingableDevice(string.strip(device)))
    
signal.signal(signal.SIGCHLD,sigchildHandler)

for device in devices:
    pidToPingableDevice[device.spawn_ping()] = device
    spawning_being_performed = None

# give the pings a chance to return
endat = time.time() + pingResponseTime
duration = pingResponseTime
while duration > 0:
    try:
        time.sleep(duration)
    except:
        pass
    duration = endat - time.time()


reap()




