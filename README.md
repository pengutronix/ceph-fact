# Ceph Fact
The *ceph-fact* tool is an ansible/puppet facter script based on [42on](http://www.42on.com/) to gather diagnostic information from a Ceph cluster.

The output from the tool is json to assist in writing ansible/puppet for managing your ceph cluster.

This tool does **NOT** collect any user (object) data contents nor authentication credentials from a Ceph cluster.

## Requirements
To run the tool, the following requirements need to be met:
* Python 3.5 or higher
* python-rados, ceph and ceph-common RPM or DEB installed
* client.admin keyring present in /etc/ceph
* /etc/ceph/ceph.conf configured to connect to Ceph cluster

You can test this by running:

``ceph health``

This should output either *HEALTH_OK*, *HEALTH_WARN* or *HEALTH_ERR*.

## Where to run
This tool should be run on a machine which is able to connect to the Ceph cluster and has the *client.admin* keyring.

In most of the situations the *monitors* are the right location to run this tool.

## Running
When the requirements are met, simply run the *ceph-fact* tool:


```
root@mon01:~# ./ceph-fact.py
{
  "ceph": {
    "status": {
      "fsid": "50c175aa-18d2-4182-899a-95a73cafe6da",
      "health": {
        "status": "HEALTH_OK",
        "checks": {},
        "mutes": []
      },
      "election_epoch": 1380,
      "quorum": [
        0,
        1,
        2,
        3,
        4
      ],
      "quorum_names": [
        "marvin06",
         ...
root@mon01:~#
```

# ansible examples

## wait 1000 seconds until cluster is healthy

```
  tasks:
    - name: "Waiting til cluster is healthy!!!"
      ansible.builtin.setup:
        filter: "facter_ceph"
      delegate_to: "{{ cluster_health_host }}"
      until:
        - facter_ceph['status']['health']['status'] == 'HEALTH_OK'
      retries: 100
      delay: 10
```

## check that there are more than one ceph-manager
```
    - name: "Fail, if there is only one ceph-manager!"
      fail:
        msg: "There must be at least 2 Managers!"
      when:
        - lookup('ansible.builtin.env', 'FAILOVERRIDE') | default("") | length  == 0 
        - facter_ceph['mgr_metadata'] | length < 2
```

## Fail the active ceph manager when working on it
```
    - name: "Failover to another Ceph-Mgr if we want to reboot the active one"
      shell: "ceph mgr fail {{ item.name }}"
      when:
        - facter_ceph['mgr_stat']['active_name']  == item.name
      loop: "{{ facter_ceph['mgr_metadata'] | selectattr('container_hostname', 'equalto', inventory_hostname_short) }}"

```

# License
This tool is based on [https://github.com/42on/ceph-collect] by [42on](http://www.42on.com/) to help Ceph customers quickly.

The tool is free to use for all other purposes. It's licensed GPLv2, so please send changes back to us!
