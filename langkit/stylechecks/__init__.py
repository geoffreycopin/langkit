#! /usr/bin/env python

"""
Style-checker engine for the Langkit project.

This engine, which checks comments and docstrings is meant to be used in
addition to PEP8/GNAT checks. As a quick-n-dirty script, the details of the
algoritms are not decently commented: in order to see what this is supposed to
handle, have a look at the testsuite in the stylechecks.tests module.
"""

from __future__ import (absolute_import, division, print_function)

import argparse
import ast
import os
import os.path
import re
import sys


TERM_CODE_RE = re.compile('(\x1b\\[[^m]*m)')
RESET = '\x1b[0m'
RED = '\x1b[31m'
GREEN = '\x1b[32m'
YELLOW = '\x1b[33m'

punctuation_re = re.compile(' [!?:;]')
sphinx_role_re = re.compile(':[a-z-]+:`')

accepted_chars = [chr(c) for c in range(0x20, 0x80)]


def colored(msg, color):
    """Return a string that displays "msg" in "color" inside a terminal."""
    return '{}{}{}'.format(color, msg, RESET)


def strip_colors(msg):
    """Return "msg" with all the terminal control codes stripped."""
    while True:
        m = TERM_CODE_RE.search(msg)
        if m:
            start, end = m.span()
            msg = msg[:start] + msg[end:]
        else:
            return msg


class Report(object):

    """Container for diagnostic messages."""

    def __init__(self, enable_colors=False, file=None):
        """Create a report.

        :param bool enable_colors: Whether diagnostics should be printed with
            colors.
        :param file|None file: File in which the "output" method should write
            the report. Standard output if None.
        """
        self.file = file or sys.stdout
        self.enable_colors = enable_colors

        self.filename = None
        self.lineno = None

        self.records = []

    @property
    def context(self):
        """Return the context for the next diagnostics."""
        return (self.filename, self.lineno)

    def set_context(self, filename, lineno):
        """Set the context for the next diagnostics."""
        self.filename = filename
        self.lineno = lineno

    def add(self, message, filename=None, line=None, col=None):
        """Add a diagnostic record."""
        line = line or self.lineno
        col = col or 0
        filename = filename or self.filename
        if not self.enable_colors:
            message = strip_colors(message)
        self.records.append((
            filename, line, col, message
        ))

    def output(self):
        """Write all diagnostics to the output file."""
        for filename, lineno, colno, message in sorted(set(self.records)):
            line = '{}:{}:{} {}\n'.format(
                colored(filename, RED),
                colored(lineno, YELLOW),
                "{}:".format(colored(colno, YELLOW)) if colno else "",
                message
            )
            if not self.enable_colors:
                line = strip_colors(line)
            self.file.write(line)


def iter_lines(content):
    """Return a generator yielding (line no., string) for each line."""
    return enumerate(content.splitlines(), 1)


def indent_level(line):
    """Return the number of prefix spaces in "line"."""
    return len(line) - len(line.lstrip(' '))


class PackageChecker(object):
    """Helper to check the order of imported packages."""

    def __init__(self, report):
        self.report = report
        self.reset()

    def add(self, name):
        if self.last_package and self.last_package.lower() > name.lower():
            self.report.add(
                'Imported package "{}" must appear after "{}"'.format(
                    colored(self.last_package, GREEN),
                    colored(name, GREEN),
                )
            )
        self.last_package = name

    def reset(self):
        self.last_package = None


def check_text(report, filename, lang, first_line, text, is_comment):
    """
    Check various rules related to comments and docstrings.

    :param Report report: The report in which diagnostics must be emitted.
    :param str filename: Filename from which the text to check comes.
    :param LanguageChecker lang: language checker corresponding to "text".
    :param int first_line: Line number for the first line in "text".
    :param str text: Text on which the checks must be performed.
    :param bool is_comment: True if "text" is a comment, False if it's a
        docstring.
    """

    lines = text.split(b'\n')
    chars = set(lines[0])
    if len(chars) == 1 and chars == set(lang.comment_start):
        # This is a comment box

        # Each line must have the same length
        if lines[0] != lines[-1]:
            report.set_context(filename, first_line)
            report.add('First and last lines are not identical in comment box')

        # Each line must start and end with language comment start
        for i, line in enumerate(lines[1:-1], 1):
            report.set_context(filename, first_line + i)
            if (not line.endswith(b' ' + lang.comment_start) or
                    len(lines[0]) != len(line)):
                report.add('Badly formatted comment box')
        return

    # Otherwise, assume this is regular text
    class State(object):

        """Helper for checking state-tracking."""

        def __init__(self):
            # If in a "quote" (i.e. an indented chunk of arbitrary content),
            # this is the minium number of columns for the quoted content. None
            # otherwise.
            self.quote_indent = None

            self.first_block = True
            self.lines_count = 0
            self.last_line = None
            self.last_end = ''

            self.is_sphinx = False
            self.is_prompt = False

            self.may_be_header = False
            self.header_context = None

        def end_block(self, is_last):
            """To be called at the end of each hunk of text."""
            if (not self.last_line or
                    not self.last_line.strip() or
                    self.quote_indent is not None):
                return

            if self.may_be_header:
                if self.last_line.strip() or not is_last:
                    report.set_context(*self.header_context)
                    report.add('Multi-line comment must have a final period')
                else:
                    return

            ends = (b'.', b'?', b'!', b':', b'...', b'::')

            if is_comment:
                if ((self.lines_count > 1 or not is_last) and
                        self.last_end not in ends):
                    if self.lines_count == 1 and not is_last:
                        self.may_be_header = True
                        self.header_context = report.context
                    else:
                        report.add('Multi-line comment must have a final'
                                   ' period')
                elif (is_last and
                        self.lines_count == 1 and
                        self.first_block and
                        self.last_end == b'.' and
                        len([c for c in self.last_line if c == b'.']) == 1):
                    report.add('Single-line comment must not have a final'
                               ' period')
            elif (not self.is_sphinx and
                    not self.is_prompt and
                    self.last_end not in ends):
                report.add('Docstring sentences must end with periods')

            self.first_block = False
            self.is_sphinx = False

    def has_prompt(line):
        """Return whether "line" starts with a Python prompt."""
        return line.lstrip().startswith(b'>>> ')

    s = State()

    for i, line in iter_lines(text):
        empty_line = not line.strip()

        if s.quote_indent is not None:
            if line.startswith(b' ' * s.quote_indent) or empty_line:
                continue
            else:
                s.quote_indent = None
        elif s.is_prompt:
            if has_prompt(line):
                continue
            s.is_prompt = False

        if (line.startswith(b':type')
                or line.startswith(b':rtype:')
                or line.startswith(b'.. code')):
            s.end_block(False)
            s.is_sphinx = True
        elif line.startswith(b':param'):
            s.end_block(False)
        elif has_prompt(line):
            s.is_prompt = True
            continue
        elif not empty_line:
            s.lines_count += 1
        elif s.lines_count > 0:
            s.end_block(False)

        report.set_context(filename, first_line + i - 1)

        # Report extra space before double punctuation. The below regexp will
        # also match Sphinx role markup (:foo:`bar`), which we must not report.
        for subs in punctuation_re.finditer(line):
            match = line[subs.start(0):].strip()
            if not sphinx_role_re.match(match):
                report.add('Extra space before double punctuation')

        if line.endswith(b'::'):
            s.last_end = b'::'
            s.quote_indent = indent_level(line) + 1
        elif line.endswith(b'...'):
            s.last_end = b'...'
        elif line.startswith(b'.. '):
            s.quote_indent = indent_level(line) + 1
        elif not empty_line:
            s.last_end = line[-1:]
        s.last_line = line

    s.end_block(True)


def check_generic(report, filename, content, lang):
    """
    Perform language-agnostic ("generic") style checks.

    :param Report report: The report in which diagnostics must be emitted.
    :param str filename: Filename from which the text to check comes.
    :param LanguageChecker lang: language checker corresponding to "text".
    :param str content: Text on which the checks must be performed.
    """
    # Line list for the current block of comments
    comment_block = []

    # Line number for the first comment line
    comment_first_line = None

    # Column number for the comment block. If we are not in a block but a
    # single line of comment (i.e. we have a comment on the same line as
    # regular code), this is still None.
    comment_column = None

    def check_comment():
        """Helper to invoke check_text on the text in "comment_block".

        Reset "comment_block" afterwards.
        """
        # Remove common indentation for this block of comment
        indent = min(len(l) - len(l.lstrip())
                     for l in comment_block
                     if l.strip())

        check_text(report, filename, lang,
                   comment_first_line,

                   # Ignored lines starting with '%': they are directives for
                   # documentation generators.
                   b'\n'.join(l[indent:] for l in comment_block
                              if not l.startswith('%')),
                   True)
        comment_block[:] = []

    def start_comment():
        """
        Return (comment_column, comment_first_line) (see above) for the current
        "line".
        """
        column = None if line[:comment_start].strip() else comment_start
        first_line = i
        return (column, first_line)

    for i, line in iter_lines(content):
        report.set_context(filename, i)

        for c in line:
            if c not in accepted_chars:
                report.add('Non-ASCII characters')
                break

        if (len(line) > 80 and
                b'http://' not in line and
                b'https://' not in line):
            report.add('Too long line')
        comment_start = line.find(lang.comment_start)

        def get_comment_text():
            """Return the text contained in the comment in "line"."""
            first = comment_start + len(lang.comment_start)
            return line[first:]

        if comment_start != -1:
            if not comment_block:
                comment_column, comment_first_line = start_comment()
                comment_first_line = i
            elif (comment_column is None or
                    comment_start != comment_column):
                check_comment()
                comment_column, comment_first_line = start_comment()
            comment_block.append(get_comment_text())

        elif comment_block:
            check_comment()

    if comment_block:
        check_comment()


class LanguageChecker(object):

    """Base class for language-specific checkers."""

    # String for single-line comments starters
    comment_start = None

    # Regular expression that matches package imports
    with_re = None

    def check(self, report, filename, content, parse):
        """
        Perform style checks.

        :param Report report: The report in which diagnostics must be emitted.
        :param str filename: Filename from which the text to check comes.
        :param str content: Text on which the checks must be performed.
        :param bool parse: Whether we expect "content" to be syntactically
            correct (i.e. if we can parse it without error).
        """
        raise NotImplementedError()


class AdaLang(LanguageChecker):
    comment_start = b'--'
    with_re = re.compile(b'^with (?P<name>[a-zA-Z0-9_.]+);.*')

    def check(self, report, filename, content, parse):
        pcheck = PackageChecker(report)
        for i, line in iter_lines(content):
            report.set_context(filename, i)
            if not line.strip():
                pcheck.reset()

            m = self.with_re.match(line)
            if m:
                pcheck.add(m.group('name'))


class PythonLang(LanguageChecker):
    comment_start = b'#'
    import_re = re.compile(b'^import (?P<name>[a-zA-Z0-9_.]+)'
                           b'( as [a-zA-Z0-9_.]+)?'
                           b'(?P<remaining>.*)')
    from_import_re = re.compile(b'^from (?P<name>[a-zA-Z0-9_.]+) import.*')

    future_expected = {'absolute_import', 'division', 'print_function'}

    def check(self, report, filename, content, parse):
        self.custom_check(report, filename, content, parse)
        if os.path.exists(filename):
            self.pep8_check(report, filename)
            self.pyflakes_check(report, filename, content)

    def pep8_check(self, report, filename):
        """
        Run pep8 checks on given filename, adding pep8 reports to report.
        """
        try:
            import pep8
        except ImportError:
            return

        class CustomReport(pep8.BaseReport):
            def error(self, line_number, offset, text, check):
                report.add(text, filename, line_number, offset)

        sg = pep8.StyleGuide(
            quiet=True,
            ignore=["W503", "E121", "E123", "E126", "E226", "E24",
                    "E704", "E402", "E721"]
        )
        sg.init_report(CustomReport)
        sg.check_files([filename])

    def pyflakes_check(self, report, filename, content):
        """
        Run pyflakes on given file with given content. Add pyflakes reports to
        report.
        """

        # Just exit silently if pyflakes is not available
        try:
            from pyflakes import api, reporter
        except ImportError:
            return

        lines_map = [(None, None)]
        current = True
        for line in content.splitlines():
            if line.strip() == b"# pyflakes off":
                current = False
            elif line.strip() == b"# pyflakes on":
                current = True
            lines_map.append((current, line))

        class CustomReporter(reporter.Reporter):
            def syntaxError(self, _, msg, lineno, offset, text):
                pass

            def unexpectedError(self, filename, msg):
                pass

            def flake(self, msg):
                if lines_map[msg.lineno][0]:
                    report.add(
                        msg.message % msg.message_args, filename, msg.lineno, 0
                    )

        api.checkPath(
            filename, reporter=CustomReporter(sys.stdout, sys.stderr)
        )

    def custom_check(self, report, filename, content, parse):
        pcheck = PackageChecker(report)
        for i, line in iter_lines(content):
            report.set_context(filename, i)
            if not line.strip():
                pcheck.reset()

            m = self.import_re.match(line)
            if m:
                if m.group('remaining'):
                    report.add('Import is more complex than'
                               ' "import PACKAGE [as NAME]"')
                pcheck.add(m.group('name'))

            m = self.from_import_re.match(line)
            if m:
                pcheck.add(m.group('name'))

        if parse:
            try:
                root = ast.parse(content)
            except (SyntaxError, TypeError) as exc:
                report.add('Could not parse: {}'.format(exc))
            else:

                def node_lineno(node):
                    return getattr(node, 'lineno', 0) + 1

                future_seen = set()

                for node in ast.walk(root):
                    try:
                        docstring = ast.get_docstring(node)
                    except TypeError:
                        pass
                    else:
                        if docstring:
                            check_text(report, filename, self,
                                       node_lineno(node),
                                       docstring,
                                       False)

                    if isinstance(node, ast.ImportFrom):
                        if node.module == '__future__':
                            future_seen.update(alias.name
                                               for alias in node.names)
                        else:
                            report.set_context(filename, node_lineno(node) - 1)
                            self._check_imported_entities(report, node)

                report.set_context(filename, 1)
                if not future_seen:
                    report.add('Missing __future__ imports')
                else:
                    missing = self.future_expected - future_seen
                    extraneous = future_seen - self.future_expected
                    if missing:
                        report.add('Missing __future__ imports: {}'.format(
                            ', '.join(sorted(missing))
                        ))
                    if extraneous:
                        report.add('Extraneous __future__ imports: {}'.format(
                            ', '.join(sorted(extraneous))
                        ))

    def _check_imported_entities(self, report, import_node):
        last = None
        for alias in import_node.names:
            name = alias.name
            if last and last > name:
                report.add('Imported entity "{}" should appear after "{}"'
                           .format(last, name))
            last = name


class MakoLang(LanguageChecker):
    comment_start = b'##'

    def check(self, report, filename, content, parse):
        first_line = content.split('\n', 1)[0]
        if 'makoada' in first_line:
            ada_lang.check(report, filename, content, parse=False)
            check_generic(report, filename, content, ada_lang)
        elif 'makopython' in first_line:
            python_lang.custom_check(report, filename, content, parse=False)
            check_generic(report, filename, content, python_lang)


ada_lang = AdaLang()
python_lang = PythonLang()
mako_lang = MakoLang()


langs = {
    'ads': ada_lang,
    'adb': ada_lang,
    'py':  python_lang,
    'mako': mako_lang,
}


def check_file_content(report, filename, content):
    """
    Perform generic and language-specific style checks.

    :param Report report: The report in which diagnostics must be emitted.
    :param str filename: Filename from which the text to check comes.
    :param str content: Text on which the checks must be performed.
    """
    ext = filename.split('.')[-1]
    try:
        lang = langs[ext]
    except KeyError:
        return

    check_generic(report, filename, content, lang)
    lang.check(report, filename, content, parse=True)


def check_file(report, filename):  # pragma: no cover
    """
    Perform generic and language-specific style checks.

    :param Report report: The report in which diagnostics must be emitted.
    :param str filename: Filename from which the text to check comes.
    """
    with open(filename, 'r') as f:
        content = f.read()
    check_file_content(report, filename, content)


def excludes_match(path, excludes):
    """
    Return whether at least one item in `excludes` matches the `path`.

    :type path: str
    :type excludes: list[str]
    :rtype: bool
    """
    path = os.path.sep + path
    return any(path.endswith(os.path.sep + e)
               for e in excludes)


def traverse(report, root, excludes):  # pragma: no cover
    """
    Perform generic and language-specific style checks.

    :param Report report: The report in which diagnostics must be emitted.
    :param str root: Root directory in which the files to stylecheck are looked
        for.
    :param [str] excludes: List of path to exclude from the search of files to
        check.
    """
    for item in sorted(os.listdir(root)):
        path = os.path.join(root, item)
        if excludes_match(path, excludes):
            continue

        if os.path.isdir(path):
            traverse(report, path, excludes)
        else:
            check_file(report, os.path.relpath(path))


def main(src_root, files, dirs, excludes):
    """
    Global purpose main procedure.

    :param str langkit_root: Root directory for the Langkit source repository.
    :param list[str] files: Source files to analyze. If empty, look for all
        sources in the Langkit repository.
    :param list[str] dirs: List of directories in which to find sources to
        check.
    :param list[str] excludes: List of directories to exclude from the search.
    """
    report = Report(enable_colors=os.isatty(sys.stdout.fileno()))

    if files:
        for f in args.files:
            check_file(report, f)
    else:
        os.chdir(src_root)
        for root in dirs:
            traverse(report, root, excludes)

    report.output()


def langkit_main(langkit_root, files=[]):
    """
    Run main() on Langkit sources.
    """
    dirs = [os.path.join('contrib', 'python'),
            os.path.join('langkit'),
            os.path.join('scripts'),
            os.path.join('testsuite'),
            os.path.join('utils')]
    excludes = ['__pycache__',
                os.path.join('contrib', 'python', 'build'),
                os.path.join('langkit', 'support', 'obj'),
                'out',
                os.path.join('stylechecks', 'tests.py'),
                os.path.join('testsuite', 'out')]
    main(langkit_root, files, dirs, excludes)


args_parser = argparse.ArgumentParser(description="""
    Check the coding style for the Langkit code base.
""")
args_parser.add_argument(
    '--langkit-root',
    default=os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ),
    help='Root directory for the Langkit source repository. Used to'
         ' automatically look for source files to analyze. If not provided,'
         ' default to a path relative to the `langkit.stylechecks` package.')
args_parser.add_argument(
    'files', nargs='*',
    help='Source files to analyze. If none is provided, look for all sources'
         ' in the Langkit repository.')


if __name__ == '__main__':
    args = args_parser.parse_args()
    langkit_main(args.langkit_root, args.files)
