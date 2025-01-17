from __future__ import absolute_import, division, print_function

import enum
import os.path
import sys
import traceback

import langkit.documentation
from langkit.utils import Colors, assert_type, col


class DiagnosticStyle(enum.Enum):
    """Format for diagnostics that Langkit emits: location and text."""

    default = 'default'
    """Human-readable tracebacks."""

    gnu_full = 'gnu-full'
    """Standard GNU format with full paths."""

    gnu_base = 'gnu-base'
    """Standard GNU format with basenames."""


class Diagnostics(object):
    """
    Holder class that'll store the language definition source dir. Meant to
    be called by manage before functions depending on knowing the language
    source dir can be called.
    """
    lang_source_dir = (
        os.path.abspath(os.environ['LANGKIT_LANG_SOURCE_DIR'])
        if 'LANGKIT_LANG_SOURCE_DIR' in os.environ else
        '<invalid dir>')
    has_pending_error = False
    _is_under_langkit_cache = {}

    style = DiagnosticStyle.default
    """
    DiagnosticStyle instance to select the diagnostic representation format.

    :type: DiagnosticStyle
    """

    @classmethod
    def set_lang_source_dir(cls, lang_source_dir):
        """
        Set the language definition source directory.
        :type lang_source_dir: str
        """
        cls.lang_source_dir = lang_source_dir
        cls._is_under_langkit_cache = {}

    @classmethod
    def is_under_langkit(cls, path):
        """
        Return wether the "path" file belongs to Langkit.

        :type path: str
        :rtype: bool
        """
        try:
            return cls._is_under_langkit_cache[path]
        except KeyError:
            result = Diagnostics.lang_source_dir in os.path.abspath(path)
            cls._is_under_langkit_cache[path] = result
            return result

    @classmethod
    def set_style(cls, style):
        """
        Set the diagnostic output format.
        :type style: DiagnosticStyle
        """
        cls.style = style


class Location(object):
    """
    Holder for a location in the source code.
    """

    def __init__(self, file, line, text=''):
        self.file = file
        """
        Path to the file for this location.

        :type: str
        """

        self.line = line
        """
        Location line number (1-based).

        :type: int
        """

        self.text = text
        """
        Optional text for the line this location targets.

        :type: str
        """

        self.previous_in_callstack = None
        """
        If this location is created in the context of a call stack, link to the
        location of the previous (i.e. caller) frame in this stack. Use the
        `short_repr` property to format the whole call stack.

        :type: None|Location
        """

    @property
    def as_tuple(self):
        return (self.file, self.line)

    def __eq__(self, other):
        return self.as_tuple == other.as_tuple

    def __lt__(self, other):
        return self.as_tuple < other.as_tuple

    def __repr__(self):
        return '<Location {} {}>'.format(self.file, self.line)

    @property
    def short_repr(self):
        """
        Return a representation for this location (and its callers, if this
        info is present) as a human readable string.

        :rtype: str
        """
        # Reconstruct the call stack
        stack = []
        loc = self
        while loc is not None:
            stack.append(loc)
            loc = loc.previous_in_callstack

        return '[{}]'.format(', '.join(
            '{}:{}'.format(os.path.basename(loc.file), loc.line)
            for loc in stack))


def extract_library_location(stack=None):
    """
    Extract the location of the definition of an entity in the language
    specification from a stack trace. Use `traceback.extract_stack()` if no
    stack is provided.

    This relies on `Diagnostics.set_lang_source_dir` being called.

    :rtype: Location|None
    """
    stack = stack or traceback.extract_stack()

    # Create Location instances for each stack frame
    locs = [Location(t[0], t[1], t[3])
            for t in stack
            if Diagnostics.is_under_langkit(t[0]) and "manage.py" not in t[0]]

    # Chain Location instances together
    for prev_loc, loc in zip(locs[:-1], locs[1:]):
        loc.previous_in_callstack = prev_loc

    return locs[-1] if locs else None


context_stack = []
"""
:type: list[(str, Location, str)]
"""

context_cache = (None, [])
"""
This will be used to cache the last context stack in case of exception.
:type: (Exception, list[(str, Location)])
"""


class Context(object):
    """
    Add context for diagnostics. For the moment this context is constituted
    of a message and a location.
    """

    def __init__(self, message, location, id=""):
        """
        :param str message: The message to display when displaying the
            diagnostic, to contextualize the location.

        :param Location location: The location associated to the context.

        :param str id: A string that is meant to uniquely identify a category
            of diagnostic. Only one message (the latest) will be shown for each
            category when diagnostics are printed. If id is empty (the default)
            then the context has no category, and it will be considered
            unique, and always be shown.
        """
        self.message = message
        self.location = location
        self.id = id

    def __enter__(self):
        context_stack.append((self.message, self.location, self.id))

    def __exit__(self, exc_type, exc_value, traceback):
        del traceback
        del exc_type
        global context_cache
        if exc_value and context_cache[0] != exc_value:
            context_cache = (exc_value, context_stack[:])
        context_stack.pop()

    def __repr__(self):
        return (
            '<diagnostics.Context message={}, location={}, id={}>'.format(
                self.message, self.location, self.id
            )
        )


class DiagnosticError(Exception):
    pass


class Severity(enum.IntEnum):
    """
    Severity of a diagnostic. For the moment we have two levels, warning and
    error. A warning won't end the compilation process, and error will.
    """
    warning = 1
    error = 2
    non_blocking_error = 3


SEVERITY_COLORS = {
    Severity.warning:            Colors.YELLOW,
    Severity.error:              Colors.RED,
    Severity.non_blocking_error: Colors.RED,
}


def format_severity(severity):
    """
    :param Severity severity:
    """
    msg = ('Error'
           if severity == Severity.non_blocking_error else
           severity.name.capitalize())
    return col(msg, Colors.BOLD + SEVERITY_COLORS[severity])


def get_structured_context(recovered=False):
    """
    From the context global structures, return a structured context locations
    list.

    :rtype: list[(str, Location)]
    """
    c = context_cache[1] if recovered else context_stack
    ids = set()
    locs = set()
    msgs = []

    # We'll iterate once on diagnostic contexts, to:
    # 1. Remove those with null locations.
    # 2. Only keep one per registered id.
    # 3. Only keep one per unique (msg, location) pair.
    for msg, loc, id in reversed(c):
        if loc and (not id or id not in ids) and ((msg, loc) not in locs):
            msgs.append((msg, loc))
            ids.add(id)
            locs.add((msg, loc))

    return msgs


def print_context(recovered=False):
    """
    Print the current error context.

    Note that this makes sense only when `DiagnosticStyle.default` is enabled.
    """
    assert Diagnostics.style == DiagnosticStyle.default

    # Then we'll print the context we've kept
    last_file_info = ''
    for ctx_msg, ctx_loc in reversed(get_structured_context(recovered)):
        # We only want to show the file information one time if it is the same
        file_info = 'File "{}", '.format(col(ctx_loc.file, Colors.CYAN))
        if last_file_info == file_info:
            file_info = '  '
        else:
            last_file_info = file_info

        print ('{file_info}line {line}, {msg}'.format(
            file_info=file_info,
            line=col(ctx_loc.line, Colors.CYAN),
            msg=ctx_msg
        ))


def get_parsable_location():
    """
    Returns an error location in the common tool parsable format::

        {file}:{line}:{column}

    Depending on the diagnostic style enabled, `file` will be a base name or a
    full path. Note that this should not be run when `DiagnosticStyle.default`
    is enabled.

    :rtype: str
    """
    assert Diagnostics.style != DiagnosticStyle.default
    ctx = get_structured_context()
    if ctx:
        loc = ctx[0][1]
        path = (os.path.abspath(loc.file)
                if Diagnostics.style == DiagnosticStyle.gnu_full else
                os.path.basename(loc.file))
        return "{}:{}:1".format(path, loc.line)
    else:
        return ""


def check_source_language(predicate, message, severity=Severity.error,
                          do_raise=True, ok_for_codegen=False):
    """
    Check predicates related to the user's input in the input language
    definition. Show error messages and eventually terminate if those error
    messages are critical.

    :param bool predicate: The predicate to check.
    :param str message: The base message to display if predicate happens to
        be false.
    :param Severity severity: The severity of the diagnostic.
    :param bool do_raise: If True, raise a DiagnosticError if predicate happens
        to be false.
    :param bool ok_for_codegen: If True, allow checks to be performed during
        code generation. This is False by default as it should be an
        exceptional situation: we want, when possible, most checks to be
        performed before we attempt to emit the generated library (for
        --check-only).
    """
    from langkit.compile_context import get_context

    if not ok_for_codegen:
        ctx = get_context(or_none=True)
        assert ctx is None or ctx.emitter is None

    severity = assert_type(severity, Severity)
    indent = ' ' * 4

    if not predicate:
        message_lines = message.splitlines()
        message = '\n'.join(
            message_lines[:1] + [indent + line for line in message_lines[1:]]
        )

        if Diagnostics.style != DiagnosticStyle.default:
            print('{}: {}'.format(get_parsable_location(), message))
        else:
            print_context()
            print('{}{}: {}'.format(
                indent if context_stack else '',
                format_severity(severity),
                message
            ))
        if severity == Severity.error and do_raise:
            raise DiagnosticError()
        elif severity == Severity.non_blocking_error:
            Diagnostics.has_pending_error = True


class WarningDescriptor(object):
    """
    Embed information about a class of warnings. Allows to log warning messages
    via the `warn_if` method.
    """

    def __init__(self, name, enabled_by_default, description):
        self.name = name
        self.description = description
        self.enabled_by_default = enabled_by_default

    @property
    def enabled(self):
        """
        Return whether this warning is enabled in the current context.

        :rtype: bool
        """
        from langkit.compile_context import get_context
        return self in get_context().warnings

    def __repr__(self):
        return '<WarningDescriptor {}>'.format(self.name)

    def warn_if(self, predicate, message):
        """
        Helper around check_source_language, to raise warnings, depending on
        whether self is enabled or not in the current context.

        :param bool predicate: The predicate to check.
        :param str message: The base message to display if predicate happens to
            be false.
        """
        check_source_language(not self.enabled or not predicate, message,
                              severity=Severity.warning)


class WarningSet(object):
    """
    Set of enabled warnings.
    """

    prop_only_entities = WarningDescriptor(
        'prop-only-entities', True,
        'Warn about properties that return AST nodes.'
    )
    unused_bindings = WarningDescriptor(
        'unused-bindings', True,
        'Warn about bindings (in properties) that are unused, or the ones used'
        ' while they are declared as unused.'
    )
    unparser_bad_grammar = WarningDescriptor(
        'unparser-bad-grammar', False,
        'Warn if the grammar is not amenable to the automatic generation of an'
        ' unparser.'
    )
    unused_node_type = WarningDescriptor(
        'unused-node-type', True,
        'Warn if a node type is not used in the grammar, and is not marked as'
        ' abstract nor synthetic.'
    )
    undocumented_public_properties = WarningDescriptor(
        'undocumented-public-properties', True,
        'Warn if a public property is left undocumented.'
    )
    undocumented_nodes = WarningDescriptor(
        'undocumented-nodes', True,
        'Warn if a node is left undocumented.'
    )
    imprecise_field_type_annotations = WarningDescriptor(
        'imprecise-field-type-annotations', True,
        'Warn about parsing field type annotations that are not as precise as'
        ' they could be.'
    )
    available_warnings = [
        prop_only_entities, unused_bindings, unparser_bad_grammar,
        unused_node_type, undocumented_public_properties, undocumented_nodes,
        imprecise_field_type_annotations,
    ]

    def __init__(self):
        self.enabled_warnings = {w for w in self.available_warnings
                                 if w.enabled_by_default}

    def __repr__(self):
        return '<WarningSet [{}]>'.format(', '.join(
            w.name for w in self.enabled_warnings
        ))

    def enable(self, warning):
        """
        Enable the given warning in this WarningSet instance.

        :type warning: WarningDescriptor|str
        """
        if isinstance(warning, str):
            warning = self.lookup(warning)
        self.enabled_warnings.add(warning)

    def disable(self, warning):
        """
        Disable the given warning in this WarningSet instance.

        :type warning: WarningDescriptor|str
        """
        if isinstance(warning, str):
            warning = self.lookup(warning)
        self.enabled_warnings.discard(warning)

    def clone(self):
        """
        Return a copy of this WarningSet instance.

        :rtype: WarningSet
        """
        other = WarningSet()
        other.enabled_warnings = set(self.enabled_warnings)
        return other

    def with_enabled(self, warning):
        """
        Return a copy of this WarningSet instance where `warning` is enabled.

        :type warning: WarningDescriptor|str
        :rtype WarningSet
        """
        other = self.clone()
        other.enable(warning)
        return other

    def with_disabled(self, warning):
        """
        Return a copy of this WarningSet instance where `warning` is disabled.

        :type warning: WarningDescriptor|str
        :rtype WarningSet
        """
        other = self.clone()
        other.disable(warning)
        return other

    def __contains__(self, warning):
        """
        Return whether `warning` is enabled:

        :type: WarningDescriptor
        :rtype: bool
        """
        return warning in self.enabled_warnings

    def lookup(self, name):
        """
        Look for the WarningDescriptor whose name is `name`. Raise a ValueError
        if none matches.

        :type name: str
        :rtype warning: WarningDescriptor
        """
        for w in self.available_warnings:
            if w.name == name:
                return w
        else:
            raise ValueError('Invalid warning: {}'.format(name))

    @classmethod
    def print_list(cls, out=sys.stdout, width=None):
        """
        Display the list of available warnings in `f`.

        :param file out: File in which the list is displayed.
        :param None|int width: Width of the message. If None, use
            os.environ['COLUMNS'].
        """
        if width is None:
            try:
                width = int(os.environ['COLUMNS'])
            except (KeyError, ValueError):
                width = 80
        print('List of available warnings:', file=out)
        for w in cls.available_warnings:
            print('', file=out)
            print('* {}:'.format(w.name), file=out)
            if w.enabled_by_default:
                print('  [enabled by default]', file=out)
            print(langkit.documentation.format_text(w.description, 2, width),
                  file=out)


def check_multiple(predicates_and_messages, severity=Severity.error):
    """
    Helper around check_source_language, check multiple predicates at once.

    :param list[(bool, str)] predicates_and_messages: List of diagnostic
        tuples.
    :param Severity severity: The severity of the diagnostics.
    """
    for predicate, message in predicates_and_messages:
        check_source_language(predicate, message, severity)


def check_type(obj, typ, message=None):
    """
    Like utils.assert_type, but produces a client error instead.

    :param Any obj: The object to check.
    :param T typ: The expected type of obj.
    :param str|None message: The base message to display if type check fails.

    :rtype: T
    """
    try:
        return assert_type(obj, typ)
    except AssertionError as e:
        message = "{}\n{}".format(e.message, message) if message else e.message
        check_source_language(False, message)


def errors_checkpoint():
    """
    If there was a non-blocking error, exit the compilation process.
    """
    if Diagnostics.has_pending_error:
        Diagnostics.has_pending_error = False
        raise DiagnosticError()
