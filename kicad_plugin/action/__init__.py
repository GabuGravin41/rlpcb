"""Classic (SWIG) action plugin for the PCB editor, KiCad 7–10: toolbar button that opens RL PCB.

Opens the panel inside KiCad using wx.html2.WebView when available (a dockable-feeling
always-on-top frame), otherwise as an app window in Edge/Chrome.
"""
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (os.path.dirname(HERE), os.path.join(HERE, "..")):
    if os.path.exists(os.path.join(cand, "launcher_common.py")):
        sys.path.insert(0, cand)
        break
else:
    sys.path.insert(0, HERE)

try:
    from launcher_common import base_url, ensure_server, open_window, tell_project
except ImportError:  # launcher_common copied next to this file by the installer
    from .launcher_common import base_url, ensure_server, open_window, tell_project  # type: ignore


class RLPCBCopilot(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "RL PCB Copilot"
        self.category = "AI"
        self.description = "Open the RL PCB design copilot"
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(HERE, "rlpcb_icon.png")

    def Run(self):
        import wx
        board = pcbnew.GetBoard()
        path = board.GetFileName() if board else ""
        proj = os.path.splitext(path)[0] + ".kicad_pro" if path else ""
        try:
            ensure_server()
        except Exception as e:  # noqa
            wx.MessageBox(str(e), "RL PCB")
            return
        tell_project(proj)
        url = base_url() + "/"
        try:
            import wx.html2
            edge = getattr(wx.html2, "WebViewBackendEdge", None)
            if os.name == "nt" and not (edge and wx.html2.WebView.IsBackendAvailable(edge)):
                raise RuntimeError("no Edge WebView2 backend")  # the IE backend can't run the panel
            frame = wx.Frame(wx.GetActiveWindow(), title="RL PCB Copilot", size=(680, 780),
                             style=wx.DEFAULT_FRAME_STYLE | wx.FRAME_FLOAT_ON_PARENT)
            frame.SetMinSize(wx.Size(460, 500))
            view = wx.html2.WebView.New(frame, backend=edge) if os.name == "nt" else wx.html2.WebView.New(frame)
            view.LoadURL(url)
            frame.Show()
        except Exception:
            open_window(proj)


RLPCBCopilot().register()
