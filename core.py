# $Id$
# Copyright (c) 2009 Oliver Beckstein <orbeckst@gmail.com>
# Released under the GNU Public License 3 (or higher, your choice)
# See the file COPYING for details.

"""
:mod:`analysis.core` -- Core classes for analysis of Gromacs trajectories
=========================================================================

This documentation is mostly of interest to programmers who want to write
analysis plugins.


Programming API for plugins
---------------------------

Additional analysis capabilities are added to a
:class:`gromacs.analysis.Simulation` class with *plugin* classes. For
an example see :mod:`gromacs.analysis.plugins`.


API description
...............

Analysis capabilities can be added with plugins to the simulation class. Each
plugin is registered with the simulation class and provides at a minimum
:meth:`~Worker.run`, :meth:`~Worker.analyze`, and :meth:`~Worker.plot` methods.

A plugin consists of a subclass of :class:`Plugin`  and an associated :class:`Worker`
instance. The former is responsible for administrative tasks and documentation,
the latter implements the analysis code.

A plugin class must be derived from :class:`Plugin` and typically bears the
name that is used to access it. A plugin instance must be *registered* with a
:class:`Simulation` object. This can be done implicitly by passing the
:class:`Simulation` instance in the ``simulation`` keyword argument to the
constructor or by explicitly calling the :meth:`Plugin.register` method with
the simulation instance. Alternatively, one can also register a plugin via the
:meth:`Simulation.add_plugin` method.

Registering the plugin means that the actual worker class is added to the
:attr:`Simulation.plugins` dictionary.

A plugin must eventually obtain a pointer to the :class:`Simulation` class in
order to be able to access simulation-global parameters such as top directories
or input files.

See :class:`analysis.plugins.CysAccessibility` and
:class:`analysis.plugins._CysAccessibility` in
``analysis/plugins/CysAccessibility.py`` as examples.


API requirements
................

* Each plugin is contained in a separate module in the
  :mod:`gromacs.analysis.plugins` package. The name of the module *must* be the
  name of the plugin class in all lower case.

* The plugin name is registered in
  :const:`gromacs.analysis.plugins.__plugins__`. (Together with the file naming
  convention this allows for automatic and consistent loading.)

* The plugin itself is derived from :class:`Plugin`; the only changes are the
  doc strings and setting the :attr:`Plugin.worker_class` class attribute to a
  :class:`Worker` class.

* The corresponding worker class is derived from :class:`Worker` and must implement

  - :meth:`Worker.__init__` which can only use keyword arguments to initialize
    the plugin. It must ensure that init methods of super classes are also
    called. See the existing plugins for details.

  - :meth:`Worker.run` which typically generates the data by analyzing a
    trajectory, possibly multiple times. It should store results in files.

  - :meth:`Worker.analyze` analyzes the data generated by :meth:`Worker.run`.

  - :meth:`Worker.plot` plots the analyzed data.

  - :meth:`Worker._register_hook` (see below)

* The worker class can access parameters of the simulation via the
  :attr:`Worker.simulation` attribute that is automatically set when the plugin
  registers itself with :class:`Simulations`. However, the plugin should *not*
  rely on :attr:`~Worker.simulation` being present during initialization
  (__init__) because registration of the plugin might occur *after* init.

  This also means that one cannot use the directory methods such as
  :meth:`Worker.plugindir` because they depend on :meth:`Simulation.topdir` and
  :meth:`Simulation.plugindir`.

  Any initialization that requires access to the :class:`Simulation` instance
  should be moved into the :meth:`Worker._register_hook` method. It is called
  when the plugin is actually being registered. Note that the hook *must* also
  call the hook of the super class before setting any values. The hook should
  pop any arguments that it requires and ignore everything else.

* Parameters of the plugin are stored in :attr:`Worker.parameters` (either as
  attributes or as key/value pairs, see the container class
  :class:`gromacs.utilities.AttributeDict`).

* Results are stored in :attr:`Worker.results` (also a :class:`gromacs.utilities.AttributeDict`).


Classes
-------

.. autoclass:: Simulation
   :members: add_plugin, set_plugin, get_plugin, run,
             analyze, plot, run_all, analyze_all, _apply_all,
             topdir, plugindir, check_file, has_plugin,
             check_plugin_name, current_plugin
   :show-inheritance:

.. autoclass:: Plugin
   :members: worker_class, register

   .. attribute:: Plugin.plugin_name

      Name of the plugin; this must be a *unique* identifier across
      all plugins of a :class:`Simulation` object. It should also be
      human understandable and must be a valid python identifier as it
      is used as a dict key.

   .. attribute:: Plugin.simulation

      The :class:`Simulation` instance who owns the plugin. Can be
      ``None`` until a successful call to :meth:`~Plugin.register`.

   .. attribute:: Plugin.worker

      The :class:`Worker` instance of the plugin.


.. autoclass:: Worker
   :members: topdir, plugindir, savefig, _register_hook
   :show-inheritance:

"""
__docformat__ = "restructuredtext en"

import sys
import os
import errno
import subprocess
import warnings

from gromacs.utilities import FileUtils, AttributeDict, asiterable

import logging
logger = logging.getLogger("gromacs.analysis")

class Simulation(object):
    """Class that represents one simulation.

    Analysis capabilities are added via plugins.

    1. Set the *active plugin* with the :meth:`Simulation.set_plugin` method.
    2. Analyze the trajectory with the active plugin by calling the
       :meth:`Simulation.run` method.
    3. Analyze the output from :meth:`run` with :meth:`Simulation.analyze`; results are stored
       in the plugin's :attr:`~Worker.results` dictionary.
    4. Plot results with :meth:`Simulation.plot`.
    """
    # NOTE: not suitable for multiple inheritance

    def __init__(self, **kwargs):
        """Set up a Simulation object.

        :Keywords:
           *sim*
             Any object that contains the attributes *tpr*, *xtc*,
             and optionally *ndx*
             (e.g. :class:`gromacs.cbook.Transformer`). The individual keywords such
             as *xtc* override the values in *sim*.
           *tpr*
             Gromacs tpr file (**required**)
           *xtc*
             Gromacs trajectory, can also be a trr (**required**)
           *edr*
             Gromacs energy file (only required for some plugins)
           *ndx*
             Gromacs index file
           *absolute*
             ``True``: Turn file names into absolute paths (typically required
             for most plugins); ``False`` keep a they are [``True``]
           *strict*
             ``True``: missing required file keyword raises a :exc:`TypeError`
             and missing the file itself raises a :exc:`IOError`.  ``False``:
             missing required files only give a warning. [``True``]
           *analysisdir*
             directory under which derived data are stored;
             defaults to the directory containing the tpr [None]
           *plugins* : list
             plugin instances or tuples (*plugin class*, *kwarg dict*) or tuples
             (*plugin_class_name*, *kwarg dict*) to be used; more can be
             added later with :meth:`Simulation.add_plugin`.

        """
        logger.info("Loading simulation data")

        sim = kwargs.pop('sim', None)
        strict = kwargs.pop('strict', True)
        def getpop(attr, required=False, strict=strict):
            """Return attribute from from kwargs or sim or None"""
            val = kwargs.pop(attr, None)  # must pop from kwargs to clean it
            if val is not None:
                return val
            try:
                return sim.__getattribute__(attr)
            except AttributeError:
                if required:
                    errmsg = "Required attribute %r not found in kwargs or sim" % attr
                    if strict:
                        logger.fatal(errmsg)
                        raise TypeError(errmsg)
                    else:
                        logger.warn(errmsg+"... continuing because of strict=False")
                        warnings.warn(errmsg)
                return None

        make_absolute = kwargs.pop('absolute', True)
        def canonical(*args):
            """Join *args* and get the :func:`os.path.realpath`."""
            if None in args:
                return None
            if not make_absolute:
                return os.path.join(*args)
            return os.path.realpath(os.path.join(*args))

        # required files
        self.tpr = canonical(getpop('tpr', required=True))
        self.xtc = canonical(getpop('xtc', required=True))
        # optional files
        self.ndx = canonical(getpop('ndx'))
        self.edr = canonical(getpop('edr'))

        # check existence of required files
        resolve = "exception"
        if not strict:
            resolve = "warn"
        for v in ('tpr', 'xtc'):
            self.check_file(v, self.__getattribute__(v), resolve=resolve)

        self.analysis_dir = kwargs.pop('analysisdir', os.path.dirname(self.tpr))

        #: Registry for plugins: This dict is central.
        self.plugins = AttributeDict()
        #: Use this plugin if none is explicitly specified. Typically set with
        #: :meth:`~Simulation.set_plugin`.
        self.default_plugin_name = None

        # XXX: Or should we simply add instances and then re-register
        #      all instances using register() ?
        # XXX: ... this API should be cleaned up. It seems to be connected
        #      back and forth in vicious circles. -- OB 2009-07-10


        plugins = kwargs.pop('plugins', [])
        # list of tuples (plugin, kwargs) or just (plugin,) if no kwords
        # required (eg if plugin is an instance)
        for x in plugins:
            try:
                P, kwargs = asiterable(x)   # make sure to wrap strings, especially 2-letter ones!
            except ValueError:
                P = x
                kwargs = {}
            self.add_plugin(P, **kwargs)

        # convenience: if only a single plugin was registered we default to that one
        if len(self.plugins) == 1:
            self.set_plugin(self.plugins.keys()[0])

        # Is this needed? If done properly, kwargs should be empty by now BUT
        # because the same list is re-used for all plugins I cannot pop them in
        # the plugins. I don't think multiple inheritance would work with this
        # setup so let's not pretend it does: hence comment out the super-init
        # call:
        ## super(Simulation, self).__init__(**kwargs)
        logger.info("Simulation instance initialised:")
        logger.info(str(self))

    def add_plugin(self, plugin, **kwargs):
        """Add a plugin to the registry.

        - If *plugin* is a :class:`Plugin` instance then the
          instance is directly registered and any keyword arguments
          are ignored.

        - If *plugin* is a :class:`Plugin` class object or a
          string that can be found in :mod:`gromacs.analysis.plugins`
          then first an instance is created with the given keyword
          arguments and then registered.

        :Arguments:
            *plugin* : class or string, or instance
               If the parameter is a class then it should have been derived
               from :class:`Plugin`. If it is a string then it is taken as a
               plugin name in :mod:`gromacs.analysis.plugins` and the
               corresponding class is added. In both cases any parameters for
               initizlization should be provided.

               If *plugin* is already a :class:`Plugin` instance then the kwargs
               will be ignored.
            *kwargs*
               The kwargs are specific for the plugin and should be
               described in its documentation.
        """
        # simulation=self must be provided so that plugin knows who owns it

        try:
            plugin.register(simulation=self)
        except (TypeError, AttributeError):
            # NOTE: this except clause can mask bugs in the plugin code!!
            if type(plugin) is str:
                import plugins            # We should be able to import this safely now...
                plugin = plugins.__plugin_classes__[plugin]
            # plugin registers itself in self.plugins
            plugin(simulation=self, **kwargs)  # simulation=self is REQUIRED!


    def topdir(self,*args):
        """Returns a path under self.analysis_dir, which is guaranteed to exist.

        .. Note:: Parent dirs are created if necessary."""
        p = os.path.join(self.analysis_dir, *args)
        parent = os.path.dirname(p)
        try:
            os.makedirs(parent)
        except OSError,err:
            if err.errno != errno.EEXIST:
                raise
        return p

    def plugindir(self, plugin_name, *args):
        """Directory where the plugin creates and looks for files."""
        return self.get_plugin(plugin_name).plugindir(*args)

    def figdir(self, plugin_name, *args):
        """Directory where the plugin saves figures."""
        return self.get_plugin(plugin_name).figdir(*args)

    def check_file(self, filetype, path, resolve="exception"):
        """Raise :exc:`ValueError` if path does not exist. Uses *filetype* in message.

        :Arguments:
           *filetype*
              type of file, for error message
           *path*
              path to file
           *resolve*
              "ignore"
                   always return ``True``
              "indicate"
                   return ``True`` if it exists, ``False`` otherwise
              "warn"
                   indicate and issue a :exc:`UserWarning`
              "exception"
                   raise :exc:`IOError` if it does not exist [default]

        """
        msg = "Missing required file %(filetype)r, got %(path)r." % vars()
        def _warn(x):
            logger.warn(msg)
            warnings.warn(msg)
            return False
        def _raise(x):
            logger.error(msg)
            raise IOError(errno.ENOENT, msg, x)
        # what happens if the file does NOT exist:
        solutions = {'ignore': lambda x: True,
                     'indicate': lambda x: False,
                     'warn': _warn,
                     'warning': _warn,
                     'exception': _raise,
                     'raise': _raise,
                     }

        if path is None or not os.path.isfile(path):
            return solutions[resolve](path)
        return True

    def check_plugin_name(self,plugin_name):
        """Raises a exc:`ValueError` if *plugin_name* is not registered."""
        if not (plugin_name is None or self.has_plugin(plugin_name)):
            raise ValueError('plugin_name (%r) must be None or one of\n%r\n' % (plugin_name, self.plugins.keys()))

    def has_plugin(self,plugin_name):
        """Returns True if *plugin_name* is registered."""
        return plugin_name in self.plugins

    def set_plugin(self,plugin_name):
        """Set the plugin that should be used by default.

        If no *plugin_name* is supplied to :meth:`run`, :meth:`analyze` etc. then
        this will be used.
        """
        if plugin_name is None:
            self.default_plugin_name = None
        else:
            self.check_plugin_name(plugin_name)
            self.default_plugin_name = plugin_name
        return self.default_plugin_name

    def get_plugin(self,plugin_name=None):
        """Return valid plugin or the default for *plugin_name*=``None``."""
        self.check_plugin_name(plugin_name)
        if plugin_name is None:
            if self.default_plugin_name is None:
                raise ValueError('No default plugin was set.')
            plugin_name = self.default_plugin_name
        return self.plugins[plugin_name]

    @property
    def current_plugin(self):
        """The currently active plugin (set with :meth:`Simulation.set_plugin`)."""
        return self.get_plugin()

    def run(self,plugin_name=None,**kwargs):
        """Generate data files as prerequisite to analysis."""
        return self.get_plugin(plugin_name).run(**kwargs)

    def run_all(self,**kwargs):
        """Execute the run() method for all registered plugins."""
        return self._apply_all(self.run, **kwargs)

    def analyze(self,plugin_name=None,**kwargs):
        """Run analysis for the plugin."""
        return self.get_plugin(plugin_name).analyze(**kwargs)

    def analyze_all(self,**kwargs):
        """Execute the analyze() method for all registered plugins."""
        return self._apply_all(self.analyze, **kwargs)

    def plot(self,plugin_name=None,figure=False,**kwargs):
        """Plot all data for the selected plugin::

          plot(plugin_name, **kwargs)

        :Arguments:
           *plugin_name*
              name of the plugin to plot data from
           *figure*
              - ``True``: plot to file with default name.
              - string: use this filename (+extension for format)
              - ``False``: only display
           *kwargs*
              arguments for plugin plot function (in many cases
              provided by :meth:`gromacs.formats.XVG.plot` and
              ultimately by :func:`pylab.plot`)
        """
        kwargs['figure'] = figure
        return self.get_plugin(plugin_name).plot(**kwargs)

    def _apply_all(self, func, **kwargs):
        """Execute *func* for all plugins."""
        results = {}
        for plugin_name in self.plugins:
            results[plugin_name] = func(plugin_name=plugin_name, **kwargs)
        return results

    def __str__(self):
        return 'Simulation(tpr=%(tpr)r, xtc=%(xtc)r, edr=%(edr)r, ndx=%(ndx)r, analysisdir=%(analysis_dir)r)' % vars(self)
    def __repr__(self):
        return str(self)



# Plugin infrastructure
# ---------------------

# worker classes (used by the plugins)

class Worker(FileUtils):
    """Base class for a plugin worker."""

    def __init__(self,**kwargs):
        """Set up Worker class.

        :Keywords:
          *plugin* : instance
             The :class:`Plugin` instance that owns this worker. **Must be supplied.**
          *simulation*
             A :class:Simulation` object, required for registration,
             but can be supplied later.
          *kwargs*
             All other keyword arguments are passed to the super class.
        """

        self.plugin = kwargs.pop('plugin', None)
        """:class:`Plugin` instance that owns this Worker."""
        assert self.plugin is not None                   # must be supplied, non-opt kw arg
        self.plugin_name = self.plugin.plugin_name
        """Name of the plugin that this Worker belongs to."""

        self.simulation = kwargs.pop('simulation',None)  # eventually needed but can come after init
        self.location = self.plugin_name                 # directory name under analysisdir
        self.results = AttributeDict()                   # store results
        self.parameters = AttributeDict()                # container for options, filenames, etc...
        self.parameters.filenames = AttributeDict()
        super(Worker,self).__init__(**kwargs)

        # note: We are NOT calling self._register_hook() here; subclasses do this
        #       themselves and it *must* cascade via super(cls, self)._register_hook().

    def _register_hook(self, **kwargs):
        """Things to initialize once the :class:`Simulation` instance is known.

        The hook is called from :meth:`Plugin.register`.

        .. Note:: Subclasses should do all their :class:`Simulation` -
                  dependent initialization in their own :meth:`_register_hook` which
                  **must** call the super class hook via the :class:`super`
                  mechanism.
        """

        simulation = kwargs.pop('simulation', self.simulation)
        # XXX: should we
        # XXX: 'try: super(Worker, self)._register_hook(**kwargs) except AttributeError: pass'
        # XXX: just in case?
        if simulation is not None:
            self.simulation = simulation

    def topdir(self, *args):
        """Returns a directory located under the simulation top directory."""
        return self.simulation.topdir(*args)

    def plugindir(self, *args):
        """Returns a directory located under the plugin top directory."""
        return self.topdir(self.location, *args)

    def figdir(self, *args):
        """Returns a directory under the plugin top directory to store figures in."""
        return self.topdir('figs', *args)

    def run(self,**kwargs):
        raise NotImplementedError

    def analyze(self,**kwargs):
        raise NotImplementedError

    def plot(self,**kwargs):
        raise NotImplementedError

    def savefig(self, filename=None, ext='png'):
        """Save the current figure under the default name or *filename*.

        Uses the supplied format and extension *ext*.
        """
        import pylab
        if filename is None:
            filename = self.parameters.figname
        _filename = self.filename(filename, ext=ext, use_my_ext=True)
        pylab.savefig(_filename)
        logger.info("Saved figure as %(_filename)r." % vars())

    def store_xvg(self, name, a, **kwargs):
        """Store array *a* as :class:`~gromacs.formats.XVG` in result *name*.

        kwargs are passed to :class:`gromacs.formats.XVG`.

        This is a helper method that simplifies the task of storing
        results in the form of a numpy array as a data file on disk in
        the xmgrace format and also as a :class:`~gromacs.formats.XVG`
        instance in the :attr:`gromacs.analysis.core.Worker.results`
        dictionary.
        """
        from gromacs.formats import XVG
        kwargs.pop('filename',None)     # ignore filename
        filename = self.plugindir(name+'.xvg')
        xvg = XVG(**kwargs)
        xvg.set(a)
        xvg.write(filename)
        self.results[name] = xvg
        self.parameters.filenames[name] = filename
        return filename

    def __repr__(self):
        """Represent the worker with the plugin name."""
        return "<%s (name %s) Worker>" % (self.plugin.__class__.__name__, self.plugin_name)

# plugins:
# registers a worker class in Simulation.plugins and adds a pointer to Simulation to worker

class Plugin(object):
    """Plugin class that can be added to a :class:`Simulation` instance.

    All analysis plugins must be derived from this base class.

    If a :class:`Simulation` instance is provided to the constructore in the
    *simulation* keyword argument then the plugin instantiates and registers a
    worker class in :attr:`Simulation.plugins` and adds the :class:`Simulation`
    instance to the worker.

    Otherwise the :meth:`Plugin.register` method must be called explicitly with
    a :class:`Simulation` instance.

    The plugin class handles the administrative tasks of interfacing with the
    :class:`Simulation` class. The worker runs the analysis.

    .. Note:: If multiple Plugin instances are added to a Simulation one *must*
              set the *name* keyword argument to distinguish the
              instances. Plugins are referred to by this name in all further
              interactions with the user. There are no sanity checks:
              A newer plugin with the same *name* simply replaces the
              previous one.
    """
    #: actual plugin :class:`gromacs.analysis.core.Worker` class (name with leading underscore)
    worker_class = None

    def __init__(self,name=None,simulation=None,**kwargs):
        """Registers the plugin with the simulation class.

        Specific keyword arguments are listed below, all other kwargs
        are passed through.

        :Arguments:
           *name* : string
                Name of the plugin. Should differ for different
                instances. Defaults to the class name.
           *simulation* : Simulation instance
                The :class:`Simulation` instance that owns this plugin instance. Can be
                ``None`` but then the :meth:`register` method has to be called manually
                with a simulation instance later.
           *kwargs*
                All other keyword arguments are passed to the Worker.
        """
        if name is None:
            name = self.__class__.__name__
        self.plugin_name = name
        """Name of the plugin; this must be a **unique** identifier
        across all plugins of a :class:`Simulation` object. It should
        also be human understandable and must be a valid python
        identifier as it is used as a dict key.
        """

        logger.info("Initializing plugin %r" % self.plugin_name)

        assert issubclass(self.worker_class, Worker)   # must be a Worker

        self.__is_registered = False                   # flag so that we only register once; maybe not needed?

        kwargs['simulation'] = simulation              # allows access of plugin to globals
        kwargs['plugin'] = self                        # tell Worker who owns it
        #: The :class:`Worker` instance of the plugin.
        self.worker = self.worker_class(**kwargs)      # create Worker instance

        #: The :class:`Simulation` instance who owns the plugin. Can be ``None``
        #: until a successful call to :meth:`~Plugin.register`.
        self.simulation = simulation

        if simulation is not None:                     # can delay registration
            self.register(simulation)

        super(Plugin, self).__init__()      # maybe pointless because all kwargs go to Worker

    def register(self, simulation):
        """Register the plugin with the :class:`Simulation` instance.

        This method also ensures that the worker class knows the simulation
        instance. This is typically required for its :meth:`~Worker.run`,
        :meth:`~Worker.analyze`, and :meth:`~Worker.plot` methods.
        """

        assert simulation is not None                      # must know who we belong to
        assert self.__is_registered == False           # only register once (necessary?)

        self.simulation = simulation                   # update our own
        self.worker._register_hook(simulation=simulation)    # HACK!!! patch simulation into worker & do more
        simulation.plugins[self.plugin_name] = self.worker  # add the worker to simulation
        self._update_worker_docs()
        self.__is_registered = True

    def _update_worker_docs(self):
        # improve help by  the worker class doc to the plugin
        # one: the user mostly sees the worker via simulation.plugins
        header = "PLUGIN DOCUMENTATION"
        try:
            if self.worker.__doc__.find(header) == -1:
                self.worker.__doc__ = self.__doc__ + "\n"+header+"\n" + self.worker.__doc__
        except AttributeError:
            pass

