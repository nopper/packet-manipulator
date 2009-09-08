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

from Base import Session
from PM.Gui.Pages.AttackPage import AttackPage

class AttackSession(Session):
    session_id = 2
    session_name = "ATTACK"

    def create_ui(self):
        self.attack_page = self.add_perspective(AttackPage, True,
                                                True, False)

        self.editor_cbs.insert(0, lambda: self.attack_page.reload())

        self.pack_start(self.paned)
        self.show_all()