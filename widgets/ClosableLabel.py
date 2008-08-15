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
import gobject

from Icons import get_pixbuf

class ClosableLabel(gtk.HBox):
    __gtype_name__ = "ClosableLabel"
    __gsignals__ = {
        'close-clicked' : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, ())
    }

    __close_icon = get_pixbuf('stock-close_small')

    def __init__(self, txt):
        super(ClosableLabel, self).__init__(False, 2)

        self.label = gtk.Label(txt)
        self.label.set_use_markup(True)
        self.label.set_alignment(0, 0.5)

        self.button = gtk.Button()
        self.button.add(gtk.image_new_from_pixbuf(self.__close_icon))
        self.button.set_relief(gtk.RELIEF_NONE)
        self.button.connect('clicked', self.__on_clicked)

        self.pack_start(self.label)
        self.pack_start(self.button, False, False)

        self.show_all()

    def __on_clicked(self, button):
        self.emit('close-clicked')

gobject.type_register(ClosableLabel)
