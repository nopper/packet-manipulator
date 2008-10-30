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

import gtk

import Backend
from PM.Core.I18N import _

class InterfacesCombo(gtk.ComboBox):
    def __init__(self):
        self.store = gtk.ListStore(str, str)

        gtk.ComboBox.__init__(self, self.store)

        pix = gtk.CellRendererPixbuf()
        txt = gtk.CellRendererText()

        self.pack_start(pix, False)
        self.pack_start(txt)

        self.set_attributes(pix, stock_id=0)
        self.set_attributes(txt, markup=1)

        self.store.append([gtk.STOCK_CONNECT, _("<b>Auto</b>")])

        for iface in Backend.find_all_devs():
            self.store.append(
                [gtk.STOCK_CONNECT, iface.name]
            )

        self.set_active(0)
        self.show()

    def get_interface(self):
        id = self.get_active()

        if id <= 0:
            return None

        iter = self.get_active_iter()
        return self.store.get_value(iter, 1)
