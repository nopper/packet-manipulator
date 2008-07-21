import gtk
import Backend

from widgets.HexView import HexView
from views import UmitView

class ProtocolHierarchy(gtk.ScrolledWindow):
    def __init__(self, proto):
        gtk.ScrolledWindow.__init__(self)

        self.__create_widgets()
        self.__pack_widgets()
        self.__connect_signals()

        self.proto_icon = None
        self.store.append(None, [self.proto_icon, proto, proto, proto])

    def __create_widgets(self):
        self.store = gtk.TreeStore(gtk.gdk.Pixbuf, str, str, object)
        self.view = gtk.TreeView(self.store)

        pix = gtk.CellRendererPixbuf()
        txt = gtk.CellRendererText()

        col = gtk.TreeViewColumn('Name')

        col.pack_start(pix, False)
        col.pack_start(txt, True)

        col.set_attributes(pix, pixbuf=0)
        col.set_attributes(txt, text=1)

        self.view.append_column(col)

        col = gtk.TreeViewColumn('Value', gtk.CellRendererText(), text=2)
        self.view.append_column(col)

        self.view.set_grid_lines(gtk.TREE_VIEW_GRID_LINES_BOTH)
        self.view.set_enable_tree_lines(True)
        self.view.set_rules_hint(True)

    def __pack_widgets(self):
        self.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        self.set_shadow_type(gtk.SHADOW_ETCHED_IN)

        self.add(self.view)

    def __connect_signals(self):
        self.view.enable_model_drag_dest([('text/plain', 0, 0)], gtk.gdk.ACTION_COPY)
        self.view.connect('drag-data-received', self.__on_drag_data)

    def __on_drag_data(self, widget, ctx, x, y, data, info, time):
        if data and data.format == 8:
            ret = self.view.get_dest_row_at_pos(x, y)

            if not ret:
                self.store.append(None, [None, data.data, data.data, None])
            else:
                path, pos = ret
                print path, pos

            ctx.finish(True, False, time)
        else:
            ctx.finish(False, False, time)

class SessionPage(gtk.VBox):
    def __init__(self, proto_name):
        gtk.VBox.__init__(self)

        self.__create_widgets(Backend.get_proto(proto_name))
        self.__pack_widgets()
        self.__connect_signals()

    def __create_widgets(self, proto):
        self._label = gtk.Label("*" + proto.__name__)

        self.protocol = proto()

        self.vpaned = gtk.VPaned()
        self.proto_hierarchy = ProtocolHierarchy(proto)
        self.hexview = HexView()

    def __pack_widgets(self):
        self.vpaned.pack1(self.proto_hierarchy)
        self.vpaned.pack2(self.hexview)
        self.pack_start(self.vpaned)

        self.show_all()

    def __connect_signals(self):
        pass

    def get_label(self):
        return self._label

    label = property(get_label)

class SessionNotebook(gtk.Notebook):
    def __init__(self):
        gtk.Notebook.__init__(self)

        self.set_show_border(False)
        self.set_scrollable(True)

    def create_session(self, proto_name):
        session = SessionPage(proto_name)
        self.append_page(session, session.label)
        self.set_tab_reorderable(session, True)

class MainTab(UmitView):
    def __create_widgets(self):
        "Create the widgets"
        self.vbox = gtk.VBox()
        self.session_notebook = SessionNotebook()

    def __pack_widgets(self):
        "Pack the widgets"
        self.vbox.pack_start(self.session_notebook)

        self.session_notebook.drag_dest_set(
            gtk.DEST_DEFAULT_ALL,
            [('text/plain', 0, 0)],
            gtk.gdk.ACTION_COPY
        )

        self._main_widget.add(self.vbox)
        self._main_widget.show_all()

    def __connect_signals(self):
        self.session_notebook.connect('drag-data-received', self.__on_drag_data)

    def create_ui(self):
        "Create the ui"
        self.__create_widgets()
        self.__pack_widgets()
        self.__connect_signals()

    #===========================================================================

    def __on_drag_data(self, widget, ctx, x, y, data, info, time):
        "drag-data-received callback"

        if data and data.format == 8:
            proto = data.data

            if Backend.get_proto(proto):
                self.session_notebook.create_session(data.data)
                ctx.finish(True, False, time)
                return True

        ctx.finish(False, False, time)
