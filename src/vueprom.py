#!/usr/bin/env python3

import atexit
import datetime
import os
import re
import sys
import threading

from flask import Flask
from prometheus_client import make_wsgi_app, Gauge
from pyemvue import PyEmVue
from pyemvue.enums import Scale, Unit
from werkzeug.middleware.dispatcher import DispatcherMiddleware

# debugging logs
DEBUG_ENABLED = os.environ.get('VUE_DEBUG', "False").lower() == "true"

# Thread that polls our friends at Emporia for the magic numbers
poller_thread = threading.Thread()

# Prom gauge which shows our per-minute usage totals by channel
USAGE_WATTS = Gauge(f'per_min_usage_total', f'Total usage for channel in watts.', labelnames=['channel_name', 'channel_num', 'device_name', 'device_gid', ], unit="watt")

# Conversion factors
minutesInAnHour = 60
wattsInAKw = 1000.0

def log(level, msg):
    global DEBUG_ENABLED

    if level == "DEBUG" and not DEBUG_ENABLED:
        return

    now = datetime.datetime.utcnow()
    print('{} | {} | {}'.format(now, level.ljust(5), msg), flush=True)

def debug(msg):
    log("DEBUG", msg)

def info(msg):
    log("INFO", msg)

def error(msg):
    log("ERROR", msg)

# Wake up! Time to die.
def die(code=0):
    global poller_thread

    try:
        poller_thread.cancel()
    except Exception as e:
        pass

    info('Shutting down.')
    sys.exit(code)

# Handle exit signals like ctrl-c
def handle_exit(signum, frame):
    info('Caught exit signal')
    die()

# Thread to poll emporia for data
def poll_emporia(vue=None, retry_login=False, poll_interval=60):
    global poller_thread

    # retry login if needed
    if retry_login:
        try:
            debug('logging in')
            vue.login(username=os.environ.get('VUE_USERNAME'), password=os.environ.get('VUE_PASSWORD'))
            info('successfully logged in')
        except Exception as e:
            error(f'Exception occurred during login: {e}')
            info(f'skipping run and trying again in {poll_interval} seconds')
            poller_thread = threading.Timer(poll_interval, poll_emporia, kwargs={"vue":vue, "retry_login":True, "poll_interval":60,} )
            poller_thread.start()
            return

    try:
        device_list = vue.get_devices()
        debug(f"Vue: found {len(device_list)} devices.")

        # build a map of device gid to name
        devices = {}

        # Gather our devices and map the gid to name and collect all the channels for the device in one list.
        for device in device_list:
            devices[device.device_gid] = devices.get(device.device_gid, device)

            # skip the channels if we're using our same cached device entry
            if device == devices[device.device_gid]:
                continue

            # add channels to our meta-device object

            if devices[device.device_gid].channels is None:
                devices[device.device_gid].channels = []
            else:
                devices[device.device_gid].channels = devices[device.device_gid].channels + device.channels

        # iterate over our devices and record the usage per channel
        for device_gid in devices:
            device = devices[device_gid]
            device_name = device.device_name

            debug(f"Device: #{device_gid} - {device_name}: {len(device.channels)} channels.")

            # give the system time to catch up with data so ask for 15 seconds-old data.
            timestamp = datetime.datetime.utcnow() - datetime.timedelta(seconds=15)

            # fetch the per minute usage
            channels_usage = vue.get_devices_usage(device_gid, timestamp, scale=Scale.MINUTE.value, unit=Unit.KWH.value)
            debug(f"Device: {device_name}: {len(channels_usage)} usage metrics.")

            # match the number in the usage with the number in the list
            # of channels so that we can populate the data with the correct name/label

            for u in channels_usage:
                try:
                    # default is device-channel#
                    name = f'{device_name}-{u.channel_num}'
                    usage_multiplier = 1.0

                    # channel will be the matching channel, if it is found.
                    finder = lambda c: c.channel_num == u.channel_num
                    channel = next(filter(finder, device.channels))

                    # get multiplier value for later
                    usage_multiplier = channel.channel_multiplier

                    # adjust the name of the channel to "mains" if we have the 1,2,3 channel.
                    if channel.name is not None:
                        name = channel.name
                        debug(f'Channel #{u.channel_num} is named {name}.')
                    else:
                        if u.channel_num == "1,2,3":
                            name = f'{device_name} Mains'
                            debug(f'Channel #{u.channel_num} is renamed to {name}.')
                        else:
                            debug(f'Channel #{u.channel_num} has no name, using default {name}.')

                except StopIteration:
                    debug(f'Channel {u.channel_num} given in usage data but not found in list of channels for device. skipped.')
                    continue

                channel_label = re.sub(r'_+', '_', re.sub(r'[^a-z0-9_]','_', name.lower(), re.I | re.M))
                kwhUsage = u.usage * usage_multiplier
                if kwhUsage is not None:
                    watts = wattsInAKw * minutesInAnHour * kwhUsage
                    USAGE_WATTS.labels(channel_label, u.channel_num, device_name, device.device_gid).set(watts)

        info(f'Finished polling run; next run in {poll_interval} seconds.')
        poller_thread = threading.Timer(poll_interval, poll_emporia, kwargs={"vue":vue, "retry_login":False, "poll_interval":60,} )
        poller_thread.start()
    except Exception as e:
        error(f'Exception occurred: {e}')
        info('restarting poll with login retry after 5s.')
        poller_thread = threading.Timer(5, poll_emporia, kwargs={"vue":vue, "retry_login":True, "poll_interval":60,} )
        poller_thread.start()
        return


def create_app():
    global poller_thread

    app = Flask(__name__)

    # hit emporia every 60 seconds
    poll_interval = 60

    vue = PyEmVue()

    # add prometheus /metrics endpoint
    app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {
        '/metrics': make_wsgi_app()
    })
    info(f'/metrics is available; scrape away!')

    info(f'Launching first poll in 1 second.')
    poller_thread = threading.Timer(1, poll_emporia, kwargs={"vue":vue, "retry_login":True, "poll_interval":poll_interval,} )
    poller_thread.start()
    atexit.register(handle_exit)
    return app


try:
    app = create_app()
except Exception as e:
    error(f'exception {e}')
    error('Unable to log in - check VUE_USERNAME/VUE_PASSWORD')
    die(-2)
