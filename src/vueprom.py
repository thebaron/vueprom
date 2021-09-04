#!/usr/bin/env python3

import atexit
import copy
import datetime
import json
import os
import re
import sys
import threading

import botocore
from flask import Flask
from prometheus_client import make_wsgi_app, Gauge
from pyemvue import PyEmVue
from pyemvue.enums import Scale, Unit
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.serving import run_simple

poller_thread = threading.Thread()

minutesInAnHour = 60
wattsInAKw = 1000.0

USAGE_WATTS = Gauge(f'per_min_usage_total', f'Total usage for channel in watts.', labelnames=['channel', 'channel_num', 'device_name', 'device_gid', ], unit="watt")

EXCLUDED_CHANNELS = ['Balance', 'TotalUsage', ]

devices = {}

def log(level, msg):
    now = datetime.datetime.utcnow()
    print('{} | {} | {}'.format(now, level.ljust(5), msg), flush=True)

def debug(msg):
    log("INFO", msg)

def info(msg):
    log("INFO", msg)

def error(msg):
    log("ERROR", msg)

def die():
    global poller_thread

    error('Caught exit signal')
    try:
        poller_thread.cancel()
    except Exception as e:
        pass

    info('Shutting down.')
    sys.exit(0)


def handle_exit(signum, frame):
    die()

# get usage for each device
def get_usage_data(device_names, device):

    device_name = device_names.get(device.device_gid, 'Unknown Device')
    info(f'Device: #{device.device_gid} "{device_name}" has {len(device.channels.items())} channels.')

    # Recurse thru the various channels, gathering rosebuds
    for number, channel in device.channels.items():

        if number in EXCLUDED_CHANNELS:
            debug(f'Excluding data from channel "{number}".')
            continue

        if channel.nested_devices:
            for gid, dev in channel.nested_devices.items():
                debug(f'Recursing into nested devices for channel "{number}".')
                get_channel_usage(device_names, dev)

        kwhUsage = channel.usage
        if kwhUsage is not None:
            channel_label = re.sub(r'_+', '_', re.sub(r'[^a-z0-9_]','_', channel.name.lower(), re.I | re.M))
            watts = wattsInAKw * minutesInAnHour * kwhUsage
            USAGE_WATTS.labels(channel_label, number, device_name, device.device_gid).set(watts)
            info(f'Channel #{number} - {channel.name} recorded as {channel_label}.')

    # Thread to poll emporia for data
def poll_emporia(vue=None, retry_login=False, devices={}, poll_interval=60):
    global poller_thread

    # retry login if needed
    if retry_login:
        try:
            info('logging in')
            vue.login(username=os.environ.get('VUE_USERNAME'), password=os.environ.get('VUE_PASSWORD'))
            info('successfully logged in')
        except Exception as e:
            error(f'Exception occurred during login: {e}')
            info(f'skipping run and trying again in {poll_interval} seconds')
            poller_thread = threading.Timer(poll_interval, poll_emporia, kwargs={"vue":vue, "retry_login":True, "devices":devices, "poll_interval":60,} )
            poller_thread.start()
            return

    try:
        device_list = vue.get_devices()
        info(f'found {len(device_list)} devices.')

        # give the system time to catch up with data
        timestamp = datetime.datetime.utcnow() - datetime.timedelta(seconds=15)

        device_names = dict(
            filter(lambda x: x[1],
            map(lambda x:(x.device_gid, x.device_name), device_list)))

        # get the usage
        device_usage = vue.get_device_list_usage(list(map(lambda d: d.device_gid, device_list)), timestamp, scale=Scale.MINUTE.value, unit=Unit.KWH.value)

        if not device_usage:
            return

        for gid, device in device_usage.items():
            get_usage_data(device_names, device)

        info(f'Finished polling run; next run in {poll_interval} seconds.')
        poller_thread = threading.Timer(poll_interval, poll_emporia, kwargs={"vue":vue, "retry_login":False, "devices":devices, "poll_interval":60,} )
        poller_thread.start()
    except Exception as e:
        error(f'Exception occurred: {e}')
        info('restarting poll with login retry after 5s.')
        poller_thread = threading.Timer(5, poll_emporia, kwargs={"vue":vue, "retry_login":True, "devices":devices, "poll_interval":60,} )
        poller_thread.start()
        return


def create_app(devices):
    global poller_thread

    app = Flask(__name__)

    poll_interval = 60
    vue = PyEmVue()

    info(f'Launching first poll.')
    poll_emporia(vue, True, devices, 60, )
    # poller_thread = threading.Timer(1, poll_emporia, kwargs={"vue":vue, "retry_login":True, "devices":devices, "poll_interval":60,} )
    # poller_thread.start()
    # atexit.register(handle_exit)
    return app


deviceFilename = os.environ.get('VUE_DEVICES_FILE')
if deviceFilename:
    try:
        with open(deviceFilename) as deviceFile:
            devices = json.load(deviceFile)
    except FileNotFoundError:
        info(f'No device list file found at {deviceFilename}')

try:
    app = create_app(devices.get('devices', {}))
except:
    error('Unable to log in - check VUE_USERNAME/VUE_PASSWORD')
    sys.exit(-2)

# add /metrics prom dumper
app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {
    '/metrics': make_wsgi_app()
    })
