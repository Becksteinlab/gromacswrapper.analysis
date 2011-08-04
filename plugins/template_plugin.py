# $Id$
# Copyright (c) 2009 Oliver Beckstein <orbeckst@gmail.com>
# Released under the GNU Public License 3 (or higher, your choice)
# See the file COPYING for details.

"""
Template for a plugin
======================

You can use this file to write plugins that conform to the plugin API.

Names that are supposed to be changed to more sensible values have
*TEMPLATE* in their name.


.. note::

   This plugin is the canonical example for how to structure plugins that
   conform to the plugin API (see docs :mod:`gromacs.analysis.core` for
   details).

Plugin class
------------

.. autoclass:: TEMPLATEplugin
   :members: worker_class
   :undoc-members:

Worker class
------------

The worker class performs the analysis.

.. autoclass:: _TEMPLATEplugin
   :members:


"""
from __future__ import with_statement

__docformat__ = "restructuredtext en"

import os.path
import warnings

import gromacs
from gromacs.utilities import AttributeDict
from gromacs.analysis.core import Worker, Plugin

import logging
logger = logging.getLogger('gromacs.analysis.plugins.TEMPLATE')

# Worker classes that are registered via Plugins (see below)
# ----------------------------------------------------------
# These must be defined before the plugins.

class _TEMPLATEplugin(Worker):
    """TEMPLATE worker class."""

    def __init__(self,**kwargs):
        """Set up  TEMPLATE analysis.

        This is the worker class; this is where all the real analysis is done.

        :Arguments:
           *keyword_1*
               description
           *keyword_2*
               description

        """
        # specific arguments: take them before calling the super class that
        # does not know what to do with them
        ## x1 = kwargs.pop('keyword_1',None)
        ## x2 = kwargs.pop('keyword_1', 1.234)   # nm

        # super class init: do this before doing anything else
        # (also sets up self.parameters and self.results)
        super(_TEMPLATEplugin, self).__init__(**kwargs)

        # process specific parameters now and set instance variables
        # ....
        # self.parameters.filenames = { 'xxx': 'yyy', ....}
        # ....

        # self.simulation might have been set by the super class
        # already; just leave this snippet at the end. Do all
        # initialization that requires the simulation class in the
        # _register_hook() method.
        if not self.simulation is None:
            self._register_hook()

    def _register_hook(self, **kwargs):
        """Run when registering; requires simulation."""

        super(_TEMPLATEplugin, self)._register_hook(**kwargs)
        assert not self.simulation is None

        # EXAMPLES:
        # filename of the index file that we generate for the cysteines
        ## self.parameters.ndx = self.plugindir('cys.ndx')
        # output filenames for g_dist, indexed by Cys resid
        ## self.parameters.filenames = dict(\
        ##    [(resid, self.plugindir('Cys%d_OW_dist.txt.bz2' % resid))
        ##     for resid in self.parameters.cysteines])
        # default filename for the combined plot
        ## self.parameters.figname = self.figdir('mindist_S_OW')


    # override 'API' methods of base class

    def run(self, cutoff=None, force=False, **gmxargs):
        """Short description of what is performed.

        The run method typically processes trajectories and writes data files.
        """
        # filename = self.parameters.filenames['XXXX']
        # if not self.check_file_exists(filename, resolve='warning') or force:
        #    logger.info("Analyzing TEMPLATE...")

        pass


    def analyze(self,**kwargs):
        """Short description of postprocessing.

        The analyze method typically postprocesses the data files
        generated by run. Splitting the complete analysis task into
        two parts (*run* and *analyze*) is advantageous because in
        this way parameters of postprocessing steps can be easily
        changed without having to rerun the time consuming trajectory
        analysis.

        :Keywords:
          *kw1*
             description
        :Returns:  a dictionary of the results and also sets ``self.results``.
        """
        from gromacs.formats import XVG

        results = AttributeDict()

        # - Do postprocessing here.
        # - Store results of calculation in results[key] where key can be chosen freely
        #   but *must* be provided so that other functions can uniformly access results.
        # - You are encouraged to store class instances with a plot() method; if you do
        #   this then you can just don't have to change the plot() method below.
        #   For instance you can use gromacs.formats.XVG(filename) to create
        #   a object from a xvg file that knows how to plot itself.

        self.results = results
        return results

    def plot(self, **kwargs):
        """Plot all results in one graph, labelled by the result keys.

        :Keywords:
           figure
               - ``True``: save figures in the given formats
               - "name.ext": save figure under this filename (``ext`` -> format)
               - ``False``: only show on screen
           formats : sequence
               sequence of all formats that should be saved [('png', 'pdf')]
           plotargs
               keyword arguments for pylab.plot()
        """

        import pylab
        figure = kwargs.pop('figure', False)
        extensions = kwargs.pop('formats', ('pdf','png'))
        for name,result in self.results.items():
            kwargs['label'] = name
            try:
                result.plot(**kwargs)      # This requires result classes with a plot() method!!
            except AttributeError:
                warnings.warn("Sorry, plotting of result %(name)r is not implemented" % vars(),
                              category=UserWarning)
        pylab.legend(loc='best')
        if figure is True:
            for ext in extensions:
                self.savefig(ext=ext)
        elif figure:
            self.savefig(filename=figure)




# Public classes that register the worker classes
#------------------------------------------------

class TEMPLATEplugin(Plugin):
    """*TEMPLATE* plugin.

    Describe the plugin in detail here. This is what the user will
    see. Add citations etc.

    # explicitly describe the call/init signature of the plugin here;
    # note that *all* arguments are technically keyword arguments
    # (this is a requirement of the API) but if there are required
    # parameters feel free to write them without square brackets in
    # the call signature as done for parameter_1 below.
    #
    # The name and simulation parameters are always present.

    .. class:: TEMPLATEplugin(parameter_1[, kwparameter_2[, name[, simulation]]])

    :Arguments:
        *parameter_1*
            required, otherwise the plugin won't be able to do anything
        *kwparameter_2*
            this optional parameter tunes the frobbnification
        *name* : string
            plugin name (used to access it)
        *simulation* : instance
            The :class:`gromacs.analysis.Simulation` instance that owns the plugin.

    """
    worker_class = _TEMPLATEplugin


