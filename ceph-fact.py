#!/usr/bin/env python3
"""

ceph-fact is a tool based on 42on ceph-collect to gather information
from a Ceph cluster for use in ansible fact

The tool gathers information from the Ceph cluster and outputs json

Author: Wido den Hollander <wido@42on.com>
Author: Björn Lässig <b.laessig@pengutronix.de>
License: GPL2
"""

import argparse
import datetime
import sys
import shutil
import logging
import tempfile
import json
import subprocess

import re


CEPH_CONFIG_FILE = '/etc/ceph/ceph.conf'
CEPH_TIMEOUT = 10

DEFAULT_CONFIG_FILTERS = [
    '(?i)password',
    '(?i)key',
    '(?i)cert'
]
FILTER_PLACEHOLDER = "** HIDDEN **"

# Logging configuration
logging.basicConfig(stream=sys.stdout, level=logging.WARNING)

log = logging.getLogger()

try:
    import rados
except ImportError:
    if sys.version_info[0] == 3:
        log.error("rados module not found, try running with python2")
        sys.exit(1)
    else:
        log.error("rados module not found, try running with python3")
        sys.exit(1)

def read_file(filename):
    """
    :param filename: File to read contents from
    :return: File contents as a String
    """
    with open(filename, 'r') as file_handle:
        return file_handle.read()


def get_rados_connection(ceph_config, timeout):
    """
    Create a connection with a Ceph cluster
    :param ceph_config: Path to ceph.conf file
    :param timeout: Seconds for timeouts on Ceph operations
    :return: Rados connection
    """
    log.debug('Using Ceph configuration file: %s', ceph_config)
    r = rados.Rados(conffile=ceph_config)

    log.debug('Setting client_mount_timeout to: %d', timeout)
    r.conf_set('client_mount_timeout', str(timeout))

    log.debug('Connecting to Ceph cluster')
    r.connect(timeout=timeout)

    return r


def spawn(command, shell=True):
    """
    Simply spawn a process and return the output
    """
    p = subprocess.Popen(command, stdout=subprocess.PIPE, shell=shell)
    (result, _) = p.communicate()
    return result.strip()


def ceph_mon_command(r, command, timeout, **kwargs):
    """
    Using librados directly execute a command inside the Monitors.

    Args:
        :param r:
            The rados object connect to the cluster
        :type r: ``rados.Rados``
        :param command:
            The command to be exected by the Mon
        :type command: ``str``
        :param timeout:
            The timeout for the request
        :type  timeout: ``int``

        :param \**kwargs:
            the arguments to pass to the mon command

    Example:
        # 'ceph device get-health-metrics 130c0631-fa78-4697-9"
        ceph_mon_command(r,"device get-health-metrics", dev_id="130c0631-fa78-4697-9")
    """

    cmd = kwargs.copy()
    cmd['prefix'] = command
    cmd['format'] = 'json'
    _, buf, _ = r.mon_command(json.dumps(cmd), b'', timeout=timeout)
    return json.loads(buf.decode('utf-8'))


def get_health_info(r, timeout):
    info = dict()
    info['stat'] = ceph_mon_command(r, 'health', timeout)
    info['df'] = ceph_mon_command(r, 'df', timeout)
    info['report'] = ceph_mon_command(r, 'report', timeout)
    info['detail'] = ceph_mon_command(r, 'health', timeout, detail='detail')
    return info


def get_mon_info(r, timeout):
    info = dict()
    info['stat'] = ceph_mon_command(r, 'mon stat', timeout)
    info['dump'] = ceph_mon_command(r, 'mon dump', timeout)
    # returns binary data
    #info['map'] = ceph_mon_command(r, 'mon getmap', timeout)
    info['metadata'] = ceph_mon_command(r, 'mon metadata', timeout)
    return info


def get_osd_info(r, timeout):
    info = dict()
    info['tree'] = ceph_mon_command(r, 'osd tree', timeout)
    info['df'] = ceph_mon_command(r, 'osd df', timeout)
    info['dump'] = ceph_mon_command(r, 'osd dump', timeout)
    info['stat'] = ceph_mon_command(r, 'osd stat', timeout)
    # returns binary data
    #info['crushmap'] = ceph_mon_command(r, 'osd getcrushmap', timeout)
    #info['map'] = ceph_mon_command(r, 'osd getmap', timeout)
    info['metadata'] = ceph_mon_command(r, 'osd metadata', timeout)
    # gathering performance data is expensive
    #info['perf'] = ceph_mon_command(r, 'osd perf', timeout)
    return info


def get_mds_info(r, timeout):
    info = dict()
    info['metadata'] = ceph_mon_command(r, 'mds metadata', timeout)
    # New ceph version
    log.debug("Gathering MDS: Luminous or newer version")
    info['dump'] = ceph_mon_command(r, 'fs dump', timeout)
    # The standard output format is colorized, force to 'json-pretty'
    info['status'] = ceph_mon_command(r, 'fs status', timeout)
    return info

def get_mgr_info(r, timeout):
    info = dict()
    info['metadata'] = ceph_mon_command(r, 'mgr metadata', timeout)
    info['stat'] = ceph_mon_command(r, 'mgr stat', timeout)
    return info

def get_pg_stat_info(r, timeout):
    info = dict()
    info['stat'] = ceph_mon_command(r, 'pg stat', timeout)
    return info


def get_pg_dump_info(r, timeout):
    info = dict()
    info['dump'] = ceph_mon_command(r, 'pg dump', timeout)
    info['dump_stuck'] = ceph_mon_command(r, 'pg dump_stuck', timeout)
    return info


def get_device_info(r, timeout):
    info = dict()
    info['check_health'] = ceph_mon_command(r, 'device check-health', timeout)
    device_list_str = ceph_mon_command(r, 'device ls', timeout)
    if device_list_str:
        device_list = json.loads(device_list_str)
        for device in device_list:
            metrics_str =  ceph_mon_command(r, 'device get-health-metrics' , timeout, devid=device['devid'])
            device['metrics'] = {}
            if metrics_str:
                metrics = json.loads(metrics_str)
                metrics_keys = [k for k in metrics.keys()]
                metrics_keys.sort()
                for key in metrics_keys[-1:]:
                    device['metrics'][key] = metrics[key]
        info['status'] = json.dumps(device_list, sort_keys=True, indent=4).encode('utf-8')
    else:
        log.info('Device health info is enabled, but it seems not supported by this ceph version')
        info['status'] = b''
    return info


def get_ceph_config(ceph_config):
    return read_file(ceph_config)


def collect_ceph_information(r, ceph_config, timeout,
                            cleanup=True, device_health=False,
                            custom_config_filters=[],log_config=False):
    
    config_filters=DEFAULT_CONFIG_FILTERS
    config_filters.extend(custom_config_filters) 
    
    def filter_config(js, is_conffile):
        """
        It purges the configuration
        Args:
            :param data:
                configuraration data
            :type data: ``str``
            :param is_conffile:
                True if data is from "ceph.conf"
            :type is_conffile: ``bool``
        Return:
            bytes
        
        """
        if not js:
          return js
        for patter in config_filters:
            for index in range(len(js)-1, -1, -1):
                for key in ('name', 'section', 'value'):
                    if bool(re.search(patter, js[index][key])):
                        js[index]['value']=FILTER_PLACEHOLDER
                        break
        return js

    data = dict()

    log.info('Gathering overall Ceph information')
    data['status'] = ceph_mon_command(r, 'status', timeout)
    data['versions'] = ceph_mon_command(r, 'versions', timeout)
    data['features'] = ceph_mon_command(r, 'features', timeout)
    data['orch'] = ceph_mon_command(r, 'orch ls', timeout)
    data['orch_host'] = ceph_mon_command(r, 'orch host ls', timeout)

    data['fsid'] = r.get_fsid()
    data['config'] = filter_config(
        ceph_mon_command(r, 'config dump', timeout),
        False
    )

    log.info('Gathering Health information')
    for key, item in get_health_info(r, timeout).items():
        data['health_{0}'.format(key)] = item

    log.info('Gathering MON information')
    for key, item in get_mon_info(r, timeout).items():
        data['mon_{0}'.format(key)] = item

    log.info('Gathering OSD information')
    for key, item in get_osd_info(r, timeout).items():
        data['osd_{0}'.format(key)] = item

    log.info('Gathering PG information')
    for key, item in get_pg_stat_info(r, timeout).items():
        data['pg_{0}'.format(key)] = item

    log.info('Gathering MDS information')
    for key, item in get_mds_info(r, timeout).items():
        data['mds_{0}'.format(key)] = item

    log.info('Gathering MGR information')
    for key, item in get_mgr_info(r, timeout).items():
        data['mgr_{0}'.format(key)] = item

    if device_health:
        log.info('Gathering Device Health information')
        for key, item in get_device_info(r, timeout).items():
            data['device_{0}'.format(key)] = item
    return data


if __name__ == '__main__':
    RETURN_VALUE = 1
    PARSER = argparse.ArgumentParser(description='Ceph Collect: Gather '
                                                 'information from a Ceph '
                                                 'cluster for support desks')
    PARSER.add_argument('--ceph-config', action='store', dest='ceph_config',
                        default=CEPH_CONFIG_FILE,
                        help='Ceph Configuration file')
    PARSER.add_argument('--timeout', action='store', type=int,
                        dest='timeout',
                        default=CEPH_TIMEOUT,
                        help='Timeout for Ceph operations')
    PARSER.add_argument('--debug', action='store_true', dest='debug',
                        default=False, help='Debug logging')
    PARSER.add_argument('--no-cleanup', action='store_false', dest='cleanup',
                        default=True, help='Clean up temporary directory')
    PARSER.add_argument('--device-health-metrics', action='store_true',
                        dest='device_health_metrics', default=False,
                        help='Enable the collection of device health information')
    PARSER.add_argument('--config-filter', action='append',
                        dest='custom_config_filter',
                        help='Custom filter (python regex) for purging config dump. '
                        )
    PARSER.add_argument('--log-gathered-config', action='store_true',
                        dest='log_gathered_config', default=False,
                        help='Log on INFO the config after the purge')
    ARGS = PARSER.parse_args()

    if ARGS.debug:
        log.setLevel(logging.DEBUG)

    try:
        CNX = get_rados_connection(ceph_config=ARGS.ceph_config,
                                   timeout=ARGS.timeout)
        data = collect_ceph_information(r=CNX, ceph_config=ARGS.ceph_config,
                                 timeout=ARGS.timeout, cleanup=ARGS.cleanup,
                                 device_health=ARGS.device_health_metrics,
                                 custom_config_filters=ARGS.custom_config_filter or [],
                                 log_config=ARGS.log_gathered_config)
        #import pprint; pprint.pprint(data)
        print(json.dumps({ 'ceph': data }))
        RETURN_VALUE = 0
    except (rados.Error,
            IOError,
            KeyError,
            ValueError) as exc:
        log.error(exc)
        # FIXME: output ceph fact json error - ansible fails if facts are failing

    sys.exit(RETURN_VALUE)
