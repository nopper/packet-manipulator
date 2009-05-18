#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (C) 2008 Adriano Monteiro Marques
#
# Author: Francesco Piccinno <stack.box@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307 USA

import os
import sys
import traceback

import fcntl
import tempfile
import subprocess

from datetime import datetime
from threading import Thread, Lock, Condition

from PM.Core.Logger import log
from PM.Core.Atoms import Node, ThreadPool, Interruptable, \
                          with_decorator, defaultdict

from PM.Manager.PreferenceManager import Prefs

from PM.Backend import VirtualIFace
from PM.Backend.Scapy.wrapper import *
from PM.Backend.Scapy.packet import MetaPacket


###############################################################################
# Helper functions
###############################################################################

def run_helper(helper_type, iface, stop_count=0, stop_time=0, stop_size=0):
    """
    Start an helper process for capturing
    @param helper is integer (0 to use tcpdump, 1 to use pcapdump)
    @param iface the interface to sniff on
    @param stop_count stop process after n packets (tcpdump/dumpcap)
    @param stop_time stop process after n secs (dumpcap only)
    @param stop_size stop process after n bytes (dumpcap only)
    @return a tuple (Popen object, outfile path)
    @see subprocess module for more information
    """
    if helper_type == 0:
        helper = Prefs()['backend.tcpdump'].value

        if stop_count:
            helper += "-c %d " % stop_count

        helper += " -vU -i%s -w%s"

        log.debug("I'm using tcpdump helper to capture packets")

    else:
        helper = Prefs()['backend.dumpcap'].value

        if stop_count:
            helper += "-c %d " % stop_count

        if stop_time:
            helper += "-a duration:%d " % stop_time

        if stop_size:
            helper += "-a filesize:%d " % stop_size / 1024

        helper += " -i%s -w%s"

        log.debug("I'm using dumpcap helper to capture packets")

    outfile = tempfile.mktemp('.pcap', 'PM-')

    process = subprocess.Popen(helper % (iface, outfile), shell=True,
                               close_fds=True, stderr=subprocess.PIPE)

    if os.name != 'nt':
        log.debug("Setting O_NONBLOCK stderr file descriptor")

        flags = fcntl.fcntl(process.stderr, fcntl.F_GETFL)

        if not process.stderr.closed:
            fcntl.fcntl(process.stderr, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    # TODO: Fix code for nt system. Probably we should use
    #       PeekNamedPipe function.

    log.debug("Process spawned as `%s` with pid %d" % \
              ((helper % (iface, outfile), process.pid)))
    log.debug("Helper started on interface %s. Dumping to %s" % \
              (iface, outfile))

    return process, outfile

def kill_helper(process):
    """
    Just a dummy method to kill the process created by run_helper that supports
    version of python < 2.6
    """
    assert isinstance(process, subprocess.Popen)

    if getattr(process, 'kill', None):
        log.debug('Killing process with pid %d with kill method' % process.pid)
        process.kill()
    else:
        if os.name == 'nt':
            log.debug('Killing process with pid %d with win32.TerminateProcess'
                      % process.pid)

            # Kill the process using pywin32
            import win32api
            win32api.TerminateProcess(int(process._handle), -1)

            # Kill the process using ctypes
            #import ctypes
            #ctypes.windll.kernel32.TerminateProcess(int(process._handle), -1)
        else:
            log.debug('Killing process with pid %d with os.kill(SIGKILL) method'
                      % process.pid)

            import signal
            os.kill(process.pid, signal.SIGKILL)

def bind_reader(outfile, ts=0.5):
    """
    Create a PcapReader to handle outfile created by run_helper.
    This is generator returning None if the file is not ready, and a tuple
    (reader, file_size, position_callable) when it is.

    @param outfile the file to poll
    @param ts the time to sleep while if object is not ready
    @return
    """
    # 20 is the minimum header length for a pcap file
    while not os.path.exists(outfile) or os.stat(outfile).st_size < 20:
        log.debug("Dumpfile %s not ready. Waiting %.2f sec" % (outfile, ts))
        time.sleep(ts)
        yield None

    log.debug("Dumpfile %s seems to be ready." % outfile)
    log.debug("Creating a PcapReader object instance")

    reader = PcapReader(outfile)
    outfile_size = float(os.stat(outfile).st_size)

    if getattr(reader.f, 'fileobj', None):
        # If fileobj is present we are gzip file and we
        # need to get the absolute position not the
        # relative to the gzip file.
        position = reader.f.fileobj.tell
    else:
        position = reader.f.tell

    yield reader, outfile_size, position

def get_n_packets(process):
    """
    @param process the process helper created with run_helper
    @return the number of packets that the helper prints on the stderr >= 0
            negative on errors.
    """
    try:
        inp, out, err = select([process.stderr],
                               [process.stderr],
                               [process.stderr])
    except:
        # Here we could have select that hangs after a kill in stop
        return -1

    if process.stderr in inp:
        line = process.stderr.read()

        if not line:
            return -2

    # Here dumpcap use '\rPackets: %u ' while tcpdump 'Got %u\r'
    # over stderr file. We use simple split(' ')[1]

    try:
        return int(line.split(' ')[1])
    except:
        return -3

def get_iface_from_ip(metapacket):
    if metapacket.haslayer(IP):
        iff, a, gw = conf.route.route(metapacket.getlayer(IP).dst)
        log.debug("Using %s interface to send packet to %s" % \
                  (iff, metapacket.root.dst))
    else:
        iff = conf.iface
        log.debug("Using default %s interface" % iff)

    return iff

def get_socket_for(metapacket, want_layer_2=False, iff=None):
    # We should check if the given packet has a IP layer but not an
    # Ether one so we could send it trough layer 3

    if iff is None:
        iff = get_iface_from_ip(metapacket)

    log.debug("Interface selected: %s" % iff)

    if not metapacket.haslayer(Ether) and not want_layer_2:
        sock = conf.L3socket(iface=iff)
    else:
        log.debug("Using layer 2 socket (Ether: %s Layer 2: %s)" % \
                 (metapacket.haslayer(Ether), want_layer_2))
        sock = conf.L2socket(iface=iff)

    return sock

###############################################################################
# Analyze functions
###############################################################################

def analyze_connections(pktlist, strict=False):
    # Doesn't work with strict = True :(
    # but without strict is also more speedy so :)

    tree = {}

    for packet in pktlist:
        hashret = packet.root.hashret()
        append = False
        last = 0

        for (idx, hash, pkt) in tree:
            last = max(last, idx)

            if hash == hashret:
                lst = tree[(idx, hash, pkt)]

                if strict:
                    for child in lst:
                        if child.root.answers(packet.root):
                            lst.append(packet)
                            append = True
                            break
                else:
                    lst.append(packet)
                    append = True

                break

        if not append:
            tree[(last + 1, hashret, packet)] = []

    items = tree.items()
    items.sort()

    return [(packet, lst) for (idx, hash, packet), lst in tree.items()]

###############################################################################
# Routing related functions
###############################################################################

def route_list():
    for net, msk, gw, iface, addr in conf.route.routes:
        yield (ltoa(net), ltoa(msk), gw, iface, addr)

def reset_routes(to=None):
    """
    Reset the routes
    @param to a list of tuples in the form of (net, mask, gw, iface, outip) or
              None
    """

    if not to:
        conf.route.resync()
    else:
        conf.route.routes = []

        for (net, msk, gw, iface, outip) in to:
            # We need to pack netmask to net
            # so we need to count the bits of the netmask

            try:
                if bin(0): pass
            except NameError, ne:
                bin = lambda x: (
                                 lambda: '-' + bin(-x),
                                 lambda: '0b' + '01'[x & 1],
                                 lambda: bin(x >> 1) + '01'[x & 1]
                                )[1 + (x > 1) - (x < 0)]()

            mask = bin(struct.unpack(">L", socket.inet_aton(msk))[0])[2:]

            try:
                bits = mask.index("0")
            except:
                bits = len(mask)

            log.debug("Mask: %s -> %d bits" % (msk, bits))
            log.debug("%s/%d on %s (%s) -> %s" % (net, bits, outip, iface, gw))
            conf.route.add(net=("%s/%d" % (net, bits)), gw=gw, dev=iface)

###############################################################################
# Sniffing related functions
###############################################################################

def find_all_devs():

    # Use dnet as fallback

    if WINDOWS or DARWIN or NETBSD or OPENBSD or FREEBSD:
        ret = []

        for obj in dnet.intf():
            try:
                ret.append(
                    VirtualIFace(obj['name'], obj['link_addr'], obj['addr'])
                )
            except:
                pass

        return ret
    else:
        ifaces = get_if_list()

        ips = []
        hws = []
        for iface in ifaces:
            ip = "0.0.0.0"
            hw = "00:00:00:00:00:00"

            try:
                ip = get_if_addr(iface)
            except Exception:
                pass

            try:
                hw = get_if_hwaddr(iface)
            except Exception:
                pass

            ips.append(ip)
            hws.append(hw)

        ret = []
        for iface, ip, hw in zip(ifaces, ips, hws):
            ret.append(VirtualIFace(iface, hw, ip))

        return ret

###############################################################################
# Send Context functions
###############################################################################

class SenderConsumer(Thread, Interruptable):
    def __init__(self, socket, metapacket, count, inter, callback, udata):
        Thread.__init__(self, name="SenderConsumer")
        self.setDaemon(True)

        self.socket = socket
        self.metapacket = metapacket
        self.count = count
        self.inter = inter
        self.callback = callback
        self.udata = udata

    def run(self):
        packet = self.metapacket.root

        # If is setted to 0 we need to do an infinite loop
        # so this variable should be negative

        if not self.count:
            log.debug("This is an infinite loop.")
            self.count = -1

        try:
            while self.count:
                self.socket.send(packet)

                if self.count > 0:
                    self.count -= 1

                if self.callback(self.metapacket, self.udata) == True:
                    log.debug("The send callback want to exit")
                    return

                time.sleep(self.inter)

        except socket.error, (errno, err):
            self.callback(Exception(err), self.udata)
            return

        self.callback(None, self.udata)

    def terminate(self):
        log.debug("Forcing exit of the thread by setting count to 0")
        self.count = 0

def send_packet(metapacket, count, inter, iface, callback, udata=None):
    """
    Send a metapacket in thread context

    @param metapacket the packet to send
    @param count send n count metapackets
    @param inter interval between two consecutive sends
    @param iface the interface to use for sending
    @param callback a callback to call at each send (of type packet, udata)
           when True is returned the send thread is stopped
    @param udata the userdata to pass to the callback
    """

    try:
        sock = get_socket_for(metapacket, iff=iface)
    except socket.error, (errno, err):
        raise Exception(err)

    send_thread = SenderConsumer(sock, metapacket, count, inter, callback,
                                 udata)
    send_thread.start()

    return send_thread

###############################################################################
# SendReceive Context functions
###############################################################################

class SendReceiveConsumer(Interruptable):
    def __init__(self, ssock, rsock, metapacket, count, inter, \
                 strict, sback, rback, sudata, rudata):

        self.send_sock = ssock
        self.recv_sock = rsock
        self.metapacket = metapacket

        self.count = count
        self.scount = count
        self.running = True

        self.inter = inter
        self.strict = strict
        self.scallback = sback
        self.rcallback = rback
        self.sudata = sudata
        self.rudata = rudata

        self.rdpipe, self.wrpipe = os.pipe()
        self.rdpipe = os.fdopen(self.rdpipe)
        self.wrpipe = os.fdopen(self.wrpipe, 'w')

        self.send_thread = Thread(target=self.__send_thread)
        self.recv_thread = Thread(target=self.__recv_thread)

        self.send_thread.setDaemon(True)
        self.recv_thread.setDaemon(True)

    def __send_thread(self):
        try:
            packet = self.metapacket.root

            if not self.scount:
                log.debug("This is an infinite loop")
                self.scount = -1

            while self.scount:
                self.send_sock.send(packet)

                if self.scount > 0:
                    self.scount -= 1

                if self.scallback(self.metapacket, self.count - self.scount, \
                                  self.sudata):

                    log.debug("send callback want to exit")
                    break

                time.sleep(self.inter)
        except SystemExit:
            pass
        except Exception, err:
            log.error("Error in _sndrecv_sthread(PID: %d EXC: %s)" % \
                      (os.getpid(), str(err)))
        else:
            if PM_USE_NEW_SCAPY:
                cPickle.dump(conf.netcache, self.wrpipe)
            else:
                cPickle.dump(arp_cache, self.wrpipe)

            self.wrpipe.close()

    def __recv_thread(self):
        ans = 0
        nbrecv = 0
        notans = self.count

        force_exit = False
        packet = self.metapacket.root
        packet_hash = packet.hashret()

        inmask = [self.recv_sock, self.rdpipe]

        while self.running:

            # TODO: here would be good to separate the thins by creating
            #       different sniff private function, 1 for darwin, 1 for win,
            #       1 for linux, 1 for tcpdump helper, 1 for dumpcap helper.
            #       This should impact also on SniffContext by moving the helper
            #       related code here.

            r = None
            if FREEBSD or DARWIN:
                inp, out, err = select(inmask, [], [], 0.05)
                if len(inp) == 0 or selr.recv_sock in inp:
                    r = self.recv_sock.nonblock_recv()
            elif WINDOWS:
                r = self.recv_sock.recv(MTU)
            else:
                inp, out, err = select(inmask, [], [], None)
                if len(inp) == 0:
                    return
                if self.recv_sock in inp:
                    r = self.recv_sock.recv(MTU)
            if r is None:
                continue

            if not self.strict or r.hashret() == packet_hash and \
               r.answers(packet):

                ans += 1

                if notans:
                    notans -= 1

                if self.rcallback(MetaPacket(r), True, self.rudata):
                    force_exit = True
                    break
            else:
                nbrecv += 1

                if self.rcallback(MetaPacket(r), False, self.rudata):
                    force_exit = True
                    break

            if notans == 0:
                break

        try:
            ac = cPickle.load(self.rdpipe)
        except EOFError:
            print "Child died unexpectedly. Packets may have not been sent"
        else:
            if PM_USE_NEW_SCAPY:
                conf.netcache.update(ac)
            else:
                arp_cache.update(ac)

        if self.send_thread and self.send_thread.isAlive():
            self.send_thread.join()

        if not force_exit:
            self.rcallback(None, False, self.rudata)

    def start(self):
        self.send_thread.start()
        self.recv_thread.start()

    def terminate(self):
        log.debug("Forcing send thread to exit by setting scount to 0")
        self.scount = 0

        log.debug("Forcing recv thread to exit by closing recv_socket")
        self.running = False
        self.recv_sock.close()

    def isAlive(self):
        return self.send_thread and self.send_thread.isAlive() or \
               self.recv_thread and self.recv_thread.isAlive()

def send_receive_packet(metapacket, count, inter, iface, strict, \
                        scallback, rcallback, sudata=None, rudata=None):
    """
    Send/receive a metapacket in thread context

    @param metapacket the packet to send
    @param count send n count metapackets
    @param inter interval between two consecutive sends
    @param iface the interface where to wait for replies
    @param strict strict checking for reply
    @param callback a callback to call at each send
           (of type packet, packet_idx, udata)
    @param sudata the userdata to pass to the send callback
    @param callback a callback to call at each receive
          (of type reply_packet, is_reply, received, answers, remaining)
    @param sudata the userdata to pass to the send callback
    """
    packet = metapacket.root

    if not isinstance(packet, Gen):
        packet = SetGen(packet)

    try:
        sock = get_socket_for(metapacket, True, iface)
        sock_send = get_socket_for(metapacket, iff=iface)

        if not sock:
            raise Exception('Unable to create a valid socket')
    except socket.error, (errno, err):
        raise Exception(err)

    consumer = SendReceiveConsumer(sock_send, sock, metapacket, count,
                                   inter, strict, scallback, rcallback,
                                   sudata, rudata)
    consumer.start()

    return consumer

###############################################################################
# Sequence Context functions
###############################################################################

class SequenceConsumer(Interruptable):
    def __init__(self, tree, count, inter, iface, strict, \
                 scallback, rcallback, sudata, rudata, excback):

        assert len(tree) > 0

        self.tree = tree
        self.count = count
        self.inter = inter
        self.strict = strict
        self.iface = iface
        self.timeout = 10

        self.sockets = []
        self.recv_list = defaultdict(list)
        self.receiving = False

        self.internal = False
        self.running = Condition()

        self.pool = ThreadPool(2, 10)
        self.pool.queue_work(None, self.__notify_exc, self.__check)

        self.scallback = scallback
        self.rcallback = rcallback
        self.excback = excback

        self.sudata, self.rudata = sudata, rudata

        log.debug("%d total packets to send for %d times" % (len(tree),
                                                             self.count))

    def isAlive(self):
        return self.internal

    def stop(self):
        self.internal = False

        self.pool.stop()
        #self.pool.join_threads()

    def terminate(self):
        self.stop()

    def start(self):
        if self.internal or self.receiving:
            log.debug("Pool already started")
            return

        self.receiving = True
        self.internal = True

        self.pool.start()

    def __check(self):
        # This is a function to allow the sequence
        # to be respawned n times

        self.receiving = True
        self.running.acquire()

        if not self.count:
            log.debug("This is an infinite loop")
            self.count = -1

        while self.internal and self.count:
            self.receiving = True

            if self.count > 0:
                log.debug("Next step %d" % self.count)
            else:
                log.debug("Another loop (infinite)")

            self.__notify_send(None)
            self.pool.queue_work(None, self.__notify_exc, self.__recv_worker)

            for node in self.tree.get_children():
                log.debug("Adding first packet of the sequence")
                self.pool.queue_work(None, self.__notify_exc,
                                     self.__send_worker, node)
                break

            log.debug("Waiting recv to begin another loop")

            self.running.wait()

            if self.count > 0:
                self.count -= 1

        self.running.release()

        if not self.internal:
            log.debug("Stopping the thread pool (async)")
            self.pool.stop()

        log.debug("Finished")

    def __recv_worker(self):
        # Here we should receive the packet and check against
        # recv_list if the packet match remove from the list
        # and start another send_worker

        if self.timeout is not None:
            stoptime = time.time() + self.timeout

        while self.internal and self.receiving:
            r = []
            inmask = [socket for socket, refcount in self.sockets]

            if self.timeout is not None:
                remain = stoptime - time.time()

                if remain <= 0:
                    self.receiving = False
                    log.debug("Timeout here!")
                    break

            if not inmask:
                time.sleep(0.05)

            if FREEBSD or DARWIN:
                inp, out, err = select(inmask, [], [], 0.05)

                for sock in inp:
                    r.append(sock.nonblock_recv())

            elif WINDOWS:
                for sock in inmask:
                    r.append(sock.recv(MTU))
            else:
                # FIXME: needs a revision here! possibly packet lost
                inp, out, err = select(inmask, [], [], 0.05)

                for sock in inp:
                    r.append(sock.recv(MTU))

            if not r:
                continue

            if self.timeout is not None:
                stoptime = time.time() + self.timeout

            for precv in r:

                if precv is None:
                    continue

                is_reply = True
                my_node = None
                requested_socket = None

                if self.strict:
                    is_reply = False
                    hashret = precv.hashret()

                    if hashret in self.recv_list:
                        for (idx, sock, node) in self.recv_list[hashret]:
                            packet = node.get_data().packet.root

                            if precv.answers(packet):
                                requested_socket = sock
                                my_node = node
                                is_reply = True

                                break

                elif not self.strict and my_node is None:
                    # Get the first packet

                    list = [(v, k) for k, v in self.recv_list.items()]
                    list.sort()

                    requested_socket = list[0][0][0][1]
                    my_node = list[0][0][0][2]
                else:
                    continue

                # Now cleanup the sockets
                for idx in xrange(len(self.sockets)):
                    if self.sockets[idx][0] == requested_socket:
                        self.sockets[idx][1] -= 1

                        if self.sockets[idx][1] == 0:
                            self.sockets.remove(self.sockets[idx])

                        break

                if is_reply:
                    self.__notify_recv(my_node, MetaPacket(precv), is_reply)

                    # Queue another send thread
                    for node in my_node.get_children():
                        self.pool.queue_work(None, self.__notify_exc,
                                             self.__send_worker, node)
                else:
                    self.__notify_recv(None, MetaPacket(precv), is_reply)

        log.debug("Trying to exit")

        self.running.acquire()
        self.running.notify()
        self.running.release()

        self.receiving = False

        self.__notify_recv(None, None, False)

    def __send_worker(self, node):
        if not self.internal:
            log.debug("Discarding packet")
            return

        obj = node.get_data()

        sock = get_socket_for(obj.packet, iff=self.iface)

        if node.is_parent():
            # Here we should add the node to the dict
            # to check the the replies for a given time
            # and continue the sequence with the next
            # depth.

            try:
                idx = self.sockets.index(sock)
                self.sockets[idx][1] += 1
            except:
                self.sockets.append([sock, 1])

            key = obj.packet.root.hashret()
            self.recv_list[key].append((len(self.recv_list), sock, node))

            log.debug("Adding socket to the list for receiving my packet %s" % \
                      sock)

        sock.send(obj.packet.root)

        self.__notify_send(node)

        log.debug("Sleeping %f after send" % self.inter)
        time.sleep(self.inter + obj.inter)

        if self.internal and node.get_parent():

            parent = node.get_parent()
            next = parent.get_next_of(node)

            if next:
                log.debug("Processing next packet")
                self.pool.queue_work(None, self.__notify_exc,
                                     self.__send_worker, next)

            else:
                log.debug("Last packet of this level")
        else:
            log.debug("Last packet sent")

    def __notify_exc(self, exc):
        self.scallback = None
        self.rcallback = None

        if isinstance(exc, socket.error):
            exc = Exception(str(exc[1]))

        if self.excback:
            self.excback(exc)
        else:
            log.debug("Exception not properly handled. Dumping:")

            traceback.print_exc(file=sys.stdout)

        self.stop()

    def __notify_send(self, node):
        log.debug("Packet sent")

        if not self.scallback:
            return

        packet = None
        parent = False

        if node is not None:
            packet = node.get_data().packet
            parent = node.is_parent()

        if self.scallback(packet, parent, self.sudata):

            log.debug("send_callback want to exit")
            self.internal = False

    def __notify_recv(self, node, reply, is_reply):
        log.debug("Packet received (is reply? %s)" % is_reply)

        if not self.rcallback:
            return

        packet = None

        if node is not None:
            packet = node.get_data().packet

        if self.rcallback(packet, reply, is_reply, self.rudata):

            log.debug("recv_callback want to exit")
            self.internal = False

def execute_sequence(sequence, count, inter, iface, strict, \
                     scallback, rcallback, sudata, rudata, excback):

    consumer = SequenceConsumer(sequence, count, inter, iface, strict, \
                                scallback, rcallback, sudata, rudata, excback)
    consumer.start()

    return consumer
