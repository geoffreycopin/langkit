"""
Nose-based testcases to make sure the stylechecker works as intended. It is
also a way to make it explicit how it is intended to work...
"""

from __future__ import absolute_import, division, print_function

from collections import namedtuple
import os

from langkit.stylechecks import Report, check_file_content


# Type to instantiate for each testcase.
#
# "filename" and "content" are passed to the checkers as-is. "records" is a
# list of (line no., text) for each expected emitted diagnostic.
#
# For layout convenience, "content" is assumed to be a string whose first line
# is empty. This first line is then stripped, as well as the maximum common
# indentation. See "reindent_content".
Testcase = namedtuple('Testcase', 'filename content records')


testcases = (
    #
    # Line-wrapping testing
    #

    Testcase('line_wrap_1.py', '''
        from __future__ import absolute_import, division, print_function


        {}
    '''.format('a' * 80), []),
    Testcase('line_wrap_2.py', '''
        from __future__ import absolute_import, division, print_function

        {}
    '''.format('a' * 81), [(3, 0, 'Too long line')]),
    Testcase('line_wrap_3.py', '''
        from __future__ import absolute_import, division, print_function

        print("http://{}")
    '''.format('a' * 81), []),

    #
    # ASCII testing
    #

    Testcase('ascii_1.py', '''
        from __future__ import absolute_import, division, print_function

        # Comment with a special char: \xa0
    ''', [(3, 0, 'Non-ASCII characters')]),

    #
    # Comment box testing
    #

    Testcase('comment_box.py', '''
        from __future__ import absolute_import, division, print_function

        #######
        # Box #
        #######
    ''', []),
    Testcase('comment_box_space.py', '''
        from __future__ import absolute_import, division, print_function

        ########
        # Box  #
        ########
    ''', []),
    Testcase('comment_box.adb', '''
        ---------
        -- Box --
        ---------
    ''', []),
    Testcase('comment_box_middle_line_shorter.py', '''
        from __future__ import absolute_import, division, print_function

        #######
        # Box#
        #######
    ''', [(4, 0, 'Badly formatted comment box')]),
    Testcase('comment_box_last_line_shorter.py', '''
        from __future__ import absolute_import, division, print_function

        #######
        # Box #
        ######
    ''', [(3, 0, 'First and last lines are not identical in comment box')]),
    Testcase('comment_box_space.py', '''
        from __future__ import absolute_import, division, print_function

        ########
        # Box ##
        ########
    ''', [(4, 0, 'Badly formatted comment box')]),
    Testcase('comment_fake_box.py', '''
        from __future__ import absolute_import, division, print_function

        #
        # Header comment
        #
    ''', []),

    #
    # Packages sorting testing
    #

    Testcase('package_1.py', '''
        from __future__ import absolute_import, division, print_function

        import foo
    ''', []),
    Testcase('package_2.py', '''
        from __future__ import absolute_import, division, print_function

        import bar
        import foo
    ''', []),
    Testcase('package_3.py', '''
        from __future__ import absolute_import, division, print_function

        import foo
        import bar
    ''', [(4, 0, 'Imported package "foo" must appear after "bar"')]),
    Testcase('package_4.py', '''
        from __future__ import absolute_import, division, print_function

        import foo

        import bar
    ''', []),
    Testcase('package_5.py', '''
        from __future__ import absolute_import, division, print_function

        import foo
        import bar as zoo
    ''', [(4, 0, 'Imported package "foo" must appear after "bar"')]),

    Testcase('package_6.adb', '''
        with Foo;
        with Bar; use Bar;
    ''', [(2, 0, 'Imported package "Foo" must appear after "Bar"')]),
    Testcase('package_7.adb', '''
        with Foo;
        with ${blah};
        with Bar;
    ''', [(3, 0, 'Imported package "Foo" must appear after "Bar"')]),
    Testcase('package_8.adb', '''
        with AB;
        with Aa;
    ''', [(2, 0, 'Imported package "AB" must appear after "Aa"')]),

    #
    # Mako-specific testing
    #

    Testcase('makopython_1.mako', '''
        ## vim: ft=makopython
        import foo
        import ${blah}
        import bar
    ''', [(4, 0, 'Imported package "foo" must appear after "bar"')]),
    Testcase('makoada_1.mako', '''
        ## vim: ft=makoada
        with Foo;
        with ${blah};
        with Bar;
    ''', [(4, 0, 'Imported package "Foo" must appear after "Bar"')]),

    #
    # Comments testing
    #

    Testcase('comment_single_1.py', '''
        from __future__ import absolute_import, division, print_function

        # This is a single-line comment
    ''', []),
    Testcase('comment_single_2.py', '''
        from __future__ import absolute_import, division, print_function

        # This is a single-line comment.
    ''', [(3, 0, 'Single-line comment must not have a final period')]),
    Testcase('comment_single_3.py', '''
        from __future__ import absolute_import, division, print_function

        # This is a single-line comment...
    ''', []),
    Testcase('comment_single_4.py', '''
        from __future__ import absolute_import, division, print_function

        # This is a single-line comment!
    ''', []),
    Testcase('comment_single_5.py', '''
        from __future__ import absolute_import, division, print_function

        foo # This a trailing single-line comment.
            # This is an autonomous single-line comment.
    ''', [(3, 0, 'Single-line comment must not have a final period'),
          (4, 0, 'Single-line comment must not have a final period')]),
    Testcase('comment_single_6.py', '''
        from __future__ import absolute_import, division, print_function

        # Invalid !
    ''', [(3, 0, 'Extra space before double punctuation')]),

    Testcase('comment_multi_1.py', '''
        from __future__ import absolute_import, division, print_function

        # This is a multi-line comment.
        # Yes?
    ''', []),
    Testcase('comment_multi_2.py', '''
        from __future__ import absolute_import, division, print_function

        # This is a multi-line comment.
        # Yes
    ''', [(4, 0, 'Multi-line comment must have a final period')]),
    Testcase('comment_multi_3.py', '''
        from __future__ import absolute_import, division, print_function

        # This is a multi-line comment.
        #
        # But with an empty line.
    ''', []),
    Testcase('comment_multi_4.py', '''
        from __future__ import absolute_import, division, print_function

        # This is a multi-line comment
        #
        # But with an empty line.
    ''', [(3, 0, 'Multi-line comment must have a final period')]),
    Testcase('comment_multi_5.py', '''
        from __future__ import absolute_import, division, print_function

        # This is a multi-line comment.
        #
        # But with an empty line
    ''', [(5, 0, 'Multi-line comment must have a final period')]),
    Testcase('comment_multi_6.py', '''
        from __future__ import absolute_import, division, print_function

        # This is a multi-line comment::
        #
        #     Blah : Invalid ! No dot, free style
    ''', []),
    Testcase('comment_multi_7.py', '''
        from __future__ import absolute_import, division, print_function

        # This is a multi-line comment::
        #
        # No dot, free style
    ''', [(5, 0, 'Multi-line comment must have a final period')]),
    Testcase('comment_multi_8.py', '''
        from __future__ import absolute_import, division, print_function

        # This is a multi-line comment::
        #
        #     Blah : Invalid ! No dot, free style
        #
        # and it is correctly formatted.
    ''', []),
    Testcase('comment_multi_9.py', '''
        from __future__ import absolute_import, division, print_function

        # This is a multi-line comment::
        #
        #     Blah : Invalid ! No dot, free style
        #
        # and it is badly formatted
    ''', [(7, 0, 'Multi-line comment must have a final period')]),
    Testcase('comment_multi_10.py', '''
        from __future__ import absolute_import, division, print_function

        # This is a multi-line comment:
        #
        # >>> Blah : Invalid ! No dot, free style
    ''', []),
    Testcase('comment_multi_11.py', '''
        from __future__ import absolute_import, division, print_function

        # This is a multi-line comment:
        #
        # >>> Blah : Invalid ! No dot, free style
        #
        # This is the end of the comment.
    ''', []),

    #
    # Docstring testing
    #

    # Line numbers are sometimes imprecise, but that's because we loose precise
    # track of line numbers when getting docstrings out of AST nodes.

    Testcase('docstring_single_1.py', '''
        from __future__ import absolute_import, division, print_function

        def foo():
            """This is a single-line docstring."""
    ''', []),
    Testcase('docstring_single_2.py', '''
        from __future__ import absolute_import, division, print_function

        def foo():
            """This is a single-line docstring"""
    ''', [(4, 0, 'Docstring sentences must end with periods')]),
    Testcase('docstring_single_3.py', '''
        from __future__ import absolute_import, division, print_function

        def foo():
            """This is a single-line docstring..."""
    ''', []),
    Testcase('docstring_single_4.py', '''
        from __future__ import absolute_import, division, print_function

        def foo():
            """This is a single-line docstring!"""
    ''', []),

    Testcase('docstring_multi_1.py', '''
        from __future__ import absolute_import, division, print_function

        def foo():
            """
            This is a multi-line docstring.
            Yes?
            """
    ''', []),
    Testcase('docstring_multi_2.py', '''
        from __future__ import absolute_import, division, print_function

        def foo():
            """
            This is a multi-line docstring.
            Yes
            """
    ''', [(5, 0, 'Docstring sentences must end with periods')]),
    Testcase('docstring_multi_3.py', '''
        from __future__ import absolute_import, division, print_function

        def foo():
            """
            This is a multi-line docstring.

            But with an empty line.
            """
    ''', []),
    Testcase('docstring_multi_4.py', '''
        from __future__ import absolute_import, division, print_function

        def foo():
            """
            This is a multi-line docstring

            But with an empty line.
            """
    ''', [(4, 0, 'Docstring sentences must end with periods')]),
    Testcase('docstring_multi_5.py', '''
        from __future__ import absolute_import, division, print_function

        def foo():
            """
            This is a multi-line docstring.

            But with an empty line
            """
    ''', [(6, 0, 'Docstring sentences must end with periods')]),
    Testcase('docstring_multi_6.py', '''
        from __future__ import absolute_import, division, print_function

        def foo():
            """
            This is a multi-line docstring::

                Blah : Invalid ! No dot, free style
            """
    ''', []),
    Testcase('docstring_multi_7.py', '''
        from __future__ import absolute_import, division, print_function

        def foo():
            """
            This is a multi-line docstring::

            No dot, free style
            """
    ''', [(6, 0, 'Docstring sentences must end with periods')]),
    Testcase('docstring_multi_8.py', '''
        from __future__ import absolute_import, division, print_function

        def foo():
            """
            This is a multi-line docstring:

            >>> Blah : Invalid ! No dot, free style
            """
    ''', []),
    Testcase('docstring_multi_9.py', '''
        from __future__ import absolute_import, division, print_function

        def foo():
            """
            This is a multi-line docstring:

            >>> Blah : Invalid ! No dot, free style

            This is the end of the docstring.
            """
    ''', []),
    Testcase('docstring_multi_10.py', '''
        from __future__ import absolute_import, division, print_function

        def foo():
            """
            Documenting some function.

            :param arg: Argument.
            :type arg: str
            """
    ''', []),
    Testcase('docstring_multi_11.py', '''
        from __future__ import absolute_import, division, print_function

        def foo():
            """
            Documenting some function.

            :param arg: Argument1.
            :type arg: str

            :param arg: Argument2.
            :type arg: int
            """
    ''', []),
    Testcase('docstring_multi_12.py', '''
        from __future__ import absolute_import, division, print_function

        def foo():
            """
            Documenting some function.

            :param arg: Argument
            :type arg: str
            """
    ''', [(6, 0, 'Docstring sentences must end with periods')]),
    Testcase('docstring_multi_13.py', '''
        from __future__ import absolute_import, division, print_function

        def foo():
            """
            Documenting some function.

            :param str arg: Long description for this argument which is
                supposed to be a string.
            """
    ''', []),
    Testcase('docstring_multi_14.py', '''
        from __future__ import absolute_import, division, print_function

        def foo():
            """
            Documenting some function.

            :param str arg: Long description for this argument which is
                supposed to be a string
            """
    ''', [(7, 0, 'Docstring sentences must end with periods')]),
    Testcase('docstring_multi_15.py', '''
        from __future__ import absolute_import, division, print_function

        def foo():
            """
            Documenting some function.

            .. code:: python

                foo + bar(True)
            """
    ''', []),
    Testcase('docstring_multi_16.py', '''
        from __future__ import absolute_import, division, print_function

        def foo():
            """
            Documenting some :ref:`function <foo>`.

            And now some :ref:`code <foo>` :

            .. code:: python

                foo + bar(True)
            """
    ''', [(6, 0, 'Extra space before double punctuation')]),

    #
    # "from __future__ testing
    #

    Testcase('future_1.py', '''
        dummy = 1
    ''', [(1, 0, 'Missing __future__ imports')]),
    Testcase('future_2.py', '''
        from __future__ import absolute_import, print_function
        dummy = 1
    ''', [(1, 0, 'Missing __future__ imports: division')]),
    Testcase('future_3.py', '''
        from __future__ import absolute_import, division, print_function
        dummy = 1
    ''', []),
    Testcase('future_4.py', '''
        from __future__ import (absolute_import, division, print_function,
                                unicode_literals)
        dummy = 1
    ''', [(1, 0, 'Extraneous __future__ imports: unicode_literals')]),

    #
    # from X import Y testing
    #

    Testcase('from_import_1.py', """
        from __future__ import absolute_import, division, print_function

        from X import A, B
    """, []),

    Testcase('from_import_1.py', """
        from __future__ import absolute_import, division, print_function

        from X import B, A
    """, [(3, 0, 'Imported entity "B" should appear after "A"')]),
)


def reindent_content(tc):
    """
    Return a stripped version of "tc.content".

    The first line (which must be empty) is stripped and the common identation
    from the other lines is stripped as well.

    :param Testcase tc: Testcase to process.
    :rtype: str
    """
    lines = tc.content.rstrip().split('\n')
    assert not lines[0], (
        'First content line for {} must be empty'.format(tc.filename)
    )
    result = []
    indent = ' ' * 8
    for i, line in enumerate(lines[1:], 1):
        assert not line.strip() or line[:len(indent)] == indent, (
            'Badly indented line {} for {}'.format(i, tc.filename)
        )
        result.append(line[len(indent):])
    return '\n'.join(result)


def create_testcase(tc):
    """Return a test function for "tc"."""

    def test():
        # Pre-process content
        report = Report(enable_colors=False)
        content = reindent_content(tc)
        check_file_content(report, tc.filename, content)
        records = [
            (tc.filename, ) + rec
            for rec in tc.records
        ]

        def fmt_records(records):
            return (
                '\n'.join('  {}:{}:{}: {}'.format(*rec) for rec in records)
                if records else
                '  <no report>'
            )

        assert report.records == records, (
            'For the following source:\n'
            '{}\n'
            'Got the following report:\n'
            '{}\n'
            'But the following was expected instead:\n'
            '{}'.format(
                '\n'.join('    {}'.format(line)
                          for line in content.split('\n')),
                fmt_records(report.records), fmt_records(records)
            )
        )

    test.__name__ = tc.filename
    test.description = tc.filename
    return test
create_testcase.__test__ = False


def test_generator():
    for tc in testcases:
        yield create_testcase(tc)


def test_report_output():
    """
    Just to cover output-related code, this trivial feature itself is not
    tested otherwise.
    """
    with open(os.devnull, 'w') as f:
        for enable_colors in (False, True):
            r = Report(enable_colors, f)
            r.add('Foobar')
            r.output()
