#!/usr/bin/python
####################################################################
# PyBlame
#
# This program provides an interactive, visual wrapper for the Git
# blame command.
#
# It allows you to browse the history of a file with line-by-line
# annotations about the last time each line was modified.  Double-
# clicking on a line will show the version at the commit point the
# line was modified, and double-clicking again shows the version
# before it was modified.
#
# To install, ensure that Python 2.7 and PyQt4 are installed on your
# system:
#
# Mac:
# $ brew install python pyqt
#
# Linux:
# $ sudo apt-get install python2.7 python-qt4
#
# Usage:
# $ cd <git repo>
# $ python pyblame.py <file in git repo>
#
####################################################################


import sys
import os
import glob
import string
import re
from PyQt4.QtCore import *
from PyQt4.QtGui import *
from PyQt4 import QtGui
from subprocess import *
import shutil
import time


####################################################################
def trace(method):
    def timed(*args, **kw):
        ts = time.time()
        result = method(*args, **kw)
        te = time.time()
        # Uncomment for verbose logging
        #print("== %r (%r, %r) %2.2f sec" % (method.__name__, args, kw, te-ts))
        return result
    return timed


####################################################################
class GitModel(QObject):

    # Signals
    fileChanged = pyqtSignal()
    revChanged = pyqtSignal()

    def __init__(self, parent=None, *args):
        QObject.__init__(self, parent, *args)

        # Fields
        self.branch = "HEAD"
        self.filename = None
        self.description = None
        self.lines = []
        self.revs = []
        self.filenames = []
        self.revIdx = -1
        self.sha = None
        self.abbrev = None
        self.firstDiff = None
        self.repoRoot = self.getRepoRootPath()

    def getRepoRootPath(self):
        # Determine a path prefix to get us back to the repository root folder.
        # This is needed because the blame command needs relative paths for files that no
        # longer exist (i.e. to traverse history across file renames).
        path = ""
        root = self.execResultAsString(["git", "rev-parse", "--show-toplevel", self.branch]).splitlines()[0]
        cwd = os.getcwd()
        # Subtract the root from the CWD (and remove the first '/')
        diff = cwd[len(root)+1:]
        if len(diff) > 0:
            path = re.sub(r"[^/]+", "..", diff) + "/"
        return path

    @trace
    def setFile( self, filein ):
        self.filename = filein
        self.loadRevs()
        self.setRev(len(self.revs) - 1)
        self.fileChanged.emit()

    @trace
    def setRev( self, rev ):
        if rev == self.revIdx or rev < 0 or rev >= len(self.revs):
            return
        self.revIdx = rev
        self.sha = self.revs[self.revIdx]
        self.abbrev = self.sha[0:8]
        self.loadBlame()
        self.loadDescription()
        self.revChanged.emit()

    @trace
    def setSha(self, sha):
        index = 0
        for rev in self.revs:
            if rev.startswith(sha):
                self.setRev(index)
                break
            index += 1
        if index == len(self.revs):
            print "ERROR: couldn't find sha in log: " + sha

    def loadRevs(self):
        self.revs = []
        self.filesnames = []
        if self.filename != None:
            result = self.execResultAsList(["git", "log", "--format=%H", "--name-only", "--follow", self.branch, "--", str(self.filename)])
            # Strip blank lines
            result = [i for i in result if len(i.strip()) > 0]
            # Split the output into a list of SHAs and a list of filenames for each SHA
            for i in reversed(range(len(result) / 2)):
                self.revs.append(result[i * 2])
                self.filenames.append(result[i * 2 + 1])

    def loadBlame(self):
        if self.filename != None and self.revIdx >= 0:

            # TODO: Use absolute path, get project root folder and prepend:
            # git rev-parse --show-toplevel HEAD
            self.lines = self.execResultAsList(["git", "blame", "--follow", self.revs[self.revIdx], "--", self.repoRoot + self.filenames[self.revIdx]])
            # Find the index of the first line that changed in the current rev
            self.firstDiff = None
            index = 0
            for line in self.lines:
                if line.startswith(self.abbrev):
                    self.firstDiff = index
                    break
                index += 1

    def loadDescription(self):
        if self.filename != None and self.revIdx >= 0:
            self.description = self.execResultAsString(["git", "show", "--quiet", self.revs[self.revIdx]])

    @trace
    def execResultAsString(self, command):
        print ">> exec: " + " ".join(command)
        output = check_output(command)
        return output

    @trace
    def execResultAsList(self, command):
        print ">> exec: " + " ".join(command)
        result = check_output(command)
        lines = result.splitlines()
        return lines


####################################################################
class DescriptionTextEdit(QTextEdit):
    def __init__(self, git, parent=None):
        QTextEdit.__init__(self, parent)
        self.git = git
        self.setCurrentFont(QFont('Courier'))
        self.connect(self.git, SIGNAL("revChanged()"), self.handleRevChanged)

    def sizeHint(self):
        return QSize(400,200)

    def handleRevChanged(self):
        self.setText(self.git.description)


####################################################################
class BlameListView(QListView):

    def setModel(self, model):
        QListView.setModel(self, model)
        self.connect(model, SIGNAL("requestScroll(QModelIndex)"), self.handleRequestScroll)

    def mouseDoubleClickEvent(self, ev):
        QListView.mouseDoubleClickEvent(self, ev)
        index = self.currentIndex()
        if index != None:
            index.model().invokeAction(index)

    @trace
    def handleRequestScroll(self, index):
        self.scrollTo(index)


####################################################################
class RevisionSlider(QSlider):
    def __init__(self, git, parent=None):
        QSlider.__init__(self, Qt.Horizontal, parent)
        self.git = git
        self.setFocusPolicy(Qt.NoFocus)
        self.setTracking(False)
        self.setTickPosition(QSlider.TicksBothSides)
        self.setTickInterval(1)
        self.connect(self.git, SIGNAL("fileChanged()"), self.handleModelChanged)
        self.connect(self.git, SIGNAL("revChanged()"), self.handleModelChanged)
        self.connect(self, SIGNAL("valueChanged(int)"), self.handleValueChanged)
        self.handleModelChanged()

    def handleModelChanged(self):
        self.setMaximum(len(self.git.revs) - 1)
        self.setMinimum(0)
        self.setValue(self.git.revIdx)

    def handleValueChanged(self, value):
        self.git.setRev(value)


####################################################################
class MyListModel(QAbstractListModel):

    # Signals
    requestScroll = pyqtSignal(QModelIndex)

    def __init__(self, git, parent=None, *args):
        QAbstractListModel.__init__(self, parent, *args)
        self.git = git
        self.connect(self.git, SIGNAL("revChanged()"), self.handleRevChanged)

    def rowCount(self, parent=QModelIndex()):
        return len(self.git.lines)

    def data(self, index, role):
        if not index.isValid():
            return QVariant()
        elif role == Qt.DisplayRole:
            return QVariant(self.git.lines[index.row()])
        elif role == Qt.BackgroundRole:
            if (self.git.lines[index.row()].startswith(self.git.abbrev)):
                return QBrush(QColor(0xFF99FF99))
        elif role == Qt.FontRole:
            return QFont('courier')
        return QVariant()

    def handleRevChanged(self):
        self.reset()
        if self.git.firstDiff != None:
            self.requestScroll.emit(self.index(self.git.firstDiff))

    def invokeAction(self, index):
        if index.isValid():
            sha = self.git.lines[index.row()][0:8]
            if self.git.abbrev == sha:
                if self.git.revIdx > 0:
                    # if you click a line that changed in the current diff,
                    # show the previous version
                    self.git.setRev(self.git.revIdx - 1)
            else:
                # show the version when the line was changed
                self.git.setSha(sha)


####################################################################
class MyWindow(QMainWindow):
    def __init__(self, filein, *args):
        QWidget.__init__(self, *args)

        # create the model
        self.git = GitModel(self)
        self.model = MyListModel(self.git, self)
        self.connect(self.git, SIGNAL("fileChanged()"), self.updateTitle)

        # create the list
        lv = BlameListView()
        lv.setModel(self.model)
        self.setCentralWidget(lv)

        # create the output console
        self.model.output = DescriptionTextEdit(self.git, self)
        self.model.output.setReadOnly(True)
        dock = QDockWidget("Description", self);
        dock.setWidget( self.model.output )
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)

        # Create the revision slider
        slider = RevisionSlider(self.git, self)
        dock = QDockWidget("Revisions", self);
        dock.setWidget(slider)
        self.addDockWidget(Qt.TopDockWidgetArea, dock)

        # populate the model
        self.git.setFile( filein )

        # create menu items
        openAct = QAction("&Open...", self)
        openAct.setShortcut("Ctrl+O")
        openAct.setStatusTip("Open a file")
        self.connect(openAct, SIGNAL("triggered()"), self.openFile)

        quitAct = QAction("&Quit", self)
        quitAct.setShortcut("Ctrl+Q")
        quitAct.setStatusTip("Quit PyBlame")
        self.connect(quitAct, SIGNAL("triggered()"), SLOT("close()"))

        fileMenu = self.menuBar().addMenu("&File")
        fileMenu.addAction( openAct )
        fileMenu.addSeparator()
        fileMenu.addAction( quitAct )

        # set the size and position of main window
        self.resize(1600,1200)
        self.center()

    def center(self):
        screen = QtGui.QDesktopWidget().screenGeometry()
        size = self.geometry()
        self.move((screen.width()-size.width())/2, (screen.height()-size.height())/2)

    def openFile(self):
        default = self.git.filename
        if default == None:
            default = os.getcwd()
        filename = QFileDialog.getOpenFileName(self, "Open File", os.path.dirname(str(default)))
        if os.path.exists(filename):
            self.git.setFile( filename )

    def updateTitle(self):
        title = "PyBlame"
        filename = self.git.filename
        if filename != None:
            title = title+" - "+os.path.basename(str(filename))
        self.setWindowTitle(title)

    def commandComplete(self):
        if self.dialog != None:
            self.dialog.accept()
            self.dialog = None


####################################################################
def main():
    app = QApplication(sys.argv)

    # execute command and parse the output
    filename = None
    if len(sys.argv) < 2:
        print "Usage: pyblame.py <file>"
        print "  Note that the current working directory must be a Git repository"
        print "  and <file> must be a file in this repository."
        sys.exit(1)

    filename = sys.argv[1]

    w = MyWindow(filename)
    #w.setWindowIcon()
    w.show()
    result = app.exec_()

    sys.exit(result)


####################################################################
if __name__ == "__main__":
    main()
