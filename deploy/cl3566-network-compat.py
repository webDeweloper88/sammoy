#!/usr/bin/env python3
"""Scope exceptions to LABRIX bridge if stale nft FORWARD DROP coexists.
Never flush rules or change global forwarding policy.
"""
import subprocess

rules=[['-i','labrix-cl3566','-j','ACCEPT'],
       ['-o','labrix-cl3566','-p','tcp','--tcp-flags','ACK','ACK','-j','ACCEPT'],
       ['-o','labrix-cl3566','-p','udp','--sport','53','-j','ACCEPT'],
       ['-o','labrix-cl3566','-p','tcp','--dport','80','-j','ACCEPT']]
policy=subprocess.run(['iptables-nft','-S','FORWARD'],capture_output=True,text=True)
if policy.returncode==0 and '-P FORWARD DROP' in policy.stdout:
    for rule in rules:
        if subprocess.run(['iptables-nft','-C','FORWARD',*rule],capture_output=True).returncode:
            subprocess.run(['iptables-nft','-I','FORWARD',*rule],check=True)
