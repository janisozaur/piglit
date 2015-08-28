# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation
# files (the "Software"), to deal in the Software without
# restriction, including without limitation the rights to use,
# copy, modify, merge, publish, distribute, sublicense, and/or
# sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following
# conditions:
#
# This permission notice shall be included in all copies or
# substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY
# KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
# WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
# PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL THE AUTHOR(S) BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN
# AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF
# OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

from __future__ import print_function, absolute_import
import os
import os.path as path
import itertools
import shutil
import collections
import tempfile
import datetime
import re
import getpass
import sys
import posixpath
import errno
import textwrap
import operator

from mako.template import Template

# a local variable status exists, prevent accidental overloading by renaming
# the module
import framework.status as so
import framework.results
from framework import grouptools, backends, exceptions

__all__ = [
    'Summary',
]


def escape_filename(key):
    """Avoid reserved characters in filenames."""
    return re.sub(r'[<>:"|?*#]', '_', key)


def escape_pathname(key):
    """ Remove / and \\ from names """
    return re.sub(r'[/\\]', '_', key)


def normalize_href(href):
    """Force backward slashes in URLs."""
    return href.replace('\\', '/')


class HTMLIndex(list):
    """
    Builds HTML output to be passed to the index mako template, which will be
    rendered into HTML pages. It does this by parsing the lists provided by the
    Summary object, and returns itself, an object with one accessor, a list of
    html strings that will be printed by the mako template.
    """

    def __init__(self, summary, page):
        """
        Steps through the list of groups and tests from all of the results and
        generates a list of dicts that are passed to mako and turned into HTML
        """

        def returnList(open, close):
            """
            As HTMLIndex iterates through the groups and tests it uses this
            function to determine which groups to close (and thus reduce the
            depth of the next write) and which ones to open (thus increasing
            the depth)

            To that end one of two things happens, the path to the previous
            group (close) and the next group (open) are equal, in that event we
            don't want to open and close, becasue that will result in a
            sawtooth pattern of a group with one test followed by the same
            group with one test, over and over.  Instead we simply return two
            empty lists, which will result in writing a long list of test
            results.  The second option is that the paths are different, and
            the function determines any commonality between the paths, and
            returns the differences as close (the groups which are completly
            written) and open (the new groups to write).
            """
            common = []

            # Open and close are lists, representing the group hierarchy, open
            # being the groups that need are soon to be written, and close
            # representing the groups that have finished writing.
            if open == close:
                return [], []
            else:
                for i, j in itertools.izip_longest(open, close):
                    if i != j:
                        for k in common:
                            open.remove(k)
                            close.remove(k)
                        return open, close
                    else:
                        common.append(i)

        # set a starting depth of 1, 0 is used for 'all' so 1 is the
        # next available group
        depth = 1

        # Current dir is a list representing the groups currently being
        # written.
        currentDir = []

        # Add a new 'tab' for each result
        self._newRow()
        self.append({'type': 'other', 'text': '<td />'})
        for each in summary.results:
            href = normalize_href(os.path.join(
                escape_pathname(each.name), "index.html"))
            self.append({'type': 'other',
                         'text': '<td class="head"><b>%(name)s</b><br />'
                                 '(<a href="%(href)s">info</a>)'
                                 '</td>' % {'name': each.name,
                                            'href': href}})
        self._endRow()

        # Add the toplevel 'all' group
        self._newRow()
        self._groupRow("head", 0, 'all')
        for each in summary.results:
            self._groupResult(summary.fractions[each.name]['all'],
                              summary.status[each.name]['all'])
        self._endRow()

        # Add the groups and tests to the out list
        for key in sorted(page):

            # Split the group names and test names, then determine
            # which groups to close and which to open
            openList = key.split(grouptools.SEPARATOR)
            test = openList.pop()
            openList, closeList = returnList(openList, list(currentDir))

            # Close any groups in the close list
            # for each group closed, reduce the depth by one
            for i in reversed(closeList):
                currentDir.remove(i)
                depth -= 1

            # Open new groups
            for localGroup in openList:
                self._newRow()

                # Add the left-most column: the name of the group
                self._groupRow("head", depth, localGroup)

                # Add the group that we just opened to the currentDir, which
                # will then be used to add that group to the HTML list. If
                # there is a KeyError (the group doesn't exist), use (0, 0)
                # which will get skip. This sets the group coloring correctly
                currentDir.append(localGroup)
                for each in summary.results:
                    # Decide which fields need to be updated
                    self._groupResult(
                        summary.fractions[each.name][grouptools.join(*currentDir)],
                        summary.status[each.name][grouptools.join(*currentDir)])

                # After each group increase the depth by one
                depth += 1
                self._endRow()

            # Add the tests for the current group
            self._newRow()

            # Add the left-most column: the name of the test
            self._testRow("group", depth, test)

            # Add the result from each test result to the HTML summary If there
            # is a KeyError (a result doesn't contain a particular test),
            # return Not Run, with clas skip for highlighting
            for each in summary.results:
                # If the "group" at the top of the key heirachy contains
                # 'subtest' then it is really not a group, link to that page
                try:
                    if each.tests[grouptools.groupname(key)].subtests:
                        href = grouptools.groupname(key)
                except KeyError:
                    href = key

                href = escape_filename(href)

                try:
                    self._testResult(escape_pathname(each.name), href,
                                     summary.status[each.name][key])
                except KeyError:
                    self.append({'type': 'other',
                                 'text': '<td class="skip">Not Run</td>'})
            self._endRow()

    def _newRow(self):
        self.append({'type': 'newRow'})

    def _endRow(self):
        self.append({'type': 'endRow'})

    def _groupRow(self, cssclass, depth, groupname):
        """
        Helper function for appending new groups to be written out
        in HTML.

        This particular function is used to write the left most
        column of the summary. (the one with the indents)
        """
        self.append({'type': "groupRow",
                     'class': cssclass,
                     'indent': (1.75 * depth),
                     'text': groupname})

    def _groupResult(self, value, css):
        """
        Helper function for appending the results of groups to the
        HTML summary file.
        """
        # "Not Run" is not a valid css class replace it with skip
        if css == so.NOTRUN:
            css = 'skip'

        self.append({'type': "groupResult",
                     'class': css,
                     'text': "%s/%s" % (value[0], value[1])})

    def _testRow(self, cssclass, depth, groupname):
        """
        Helper function for appending new tests to be written out
        in HTML.

        This particular function is used to write the left most
        column of the summary. (the one with the indents)
        """
        self.append({'type': "testRow",
                     'class': cssclass,
                     'indent': (1.75 * depth),
                     'text': groupname})

    def _testResult(self, group, href, text):
        """
        Helper function for writing the results of tests

        This function writes the cells other than the left-most cell,
        displaying pass/fail/crash/etc and formatting the cell to the
        correct color.
        """
        # "Not Run" is not a valid class, if it apears set the class to skip
        if text == so.NOTRUN:
            css = 'skip'
            href = None
        else:
            css = text
            # Use posixpath for this URL because it maintains portability
            # between windows and *nix.
            href = posixpath.join(group, href + ".html")
            href = normalize_href(href)

        self.append({'type': 'testResult',
                     'class': css,
                     'href': href,
                     'text': text})


class Summary:
    """
    This Summary class creates an initial object containing lists of tests
    including all, changes, problems, skips, regressions, and fixes. It then
    uses methods to generate various kinds of output. The reference
    implementation is HTML output through mako, aptly named generateHTML().
    """
    TEMP_DIR = path.join(tempfile.gettempdir(),
                         "piglit-{}".format(getpass.getuser()),
                         'version-{}'.format(sys.version.split()[0]),
                         "html-summary")
    TEMPLATE_DIR = path.abspath(
        path.join(path.dirname(__file__), '..', 'templates'))

    def __init__(self, resultfiles):
        """
        Create an initial object with all of the result information rolled up
        in an easy to process form.

        The constructor of the summary class has an attribute for each HTML
        summary page, which are fed into the index.mako file to produce HTML
        files. resultfiles is a list of paths to JSON results generated by
        piglit-run.
        """

        # Create a Result object for each piglit result and append it to the
        # results list
        self.results = [backends.load(i) for i in resultfiles]

        self.status = {}
        self.fractions = {}
        self.tests = {'all': set(), 'changes': set(), 'problems': set(),
                      'skipped': set(), 'regressions': set(), 'fixes': set(),
                      'enabled': set(), 'disabled': set(), 'incomplete': set()}

        def fgh(test, result):
            """ Helper for updating the fractions and status lists """
            fraction[test] = tuple(
                [sum(i) for i in zip(fraction[test], result.fraction)])

            # If the new status is worse update it, or if the new status is
            # SKIP (which is equivalent to notrun) and the current is NOTRUN
            # update it
            if (status[test] < result or
                    (result == so.SKIP and status[test] == so.NOTRUN)):
                status[test] = result

        for results in self.results:
            # Create a set of all of the tset names across all of the runs
            self.tests['all'] = set(self.tests['all'] | set(results.tests))

            # Create two dictionaries that have a default factory: they return
            # a default value instead of a key error.
            # This default key must be callable
            self.fractions[results.name] = \
                collections.defaultdict(lambda: (0, 0))
            self.status[results.name] = \
                collections.defaultdict(lambda: so.NOTRUN)

            # short names
            fraction = self.fractions[results.name]
            status = self.status[results.name]

            # store the results to be appeneded to results. Adding them in the
            # loop will cause a RuntimeError
            temp_results = {}

            for key, value in results.tests.iteritems():
                # Treat a test with subtests as if it is a group, assign the
                # subtests' statuses and fractions down to the test, and then
                # proceed like normal.
                if value.subtests:
                    for (subt, subv) in value.subtests.iteritems():
                        subt = grouptools.join(key, subt)
                        subv = so.status_lookup(subv)

                        # Add the subtest to the fractions and status lists
                        fraction[subt] = subv.fraction
                        status[subt] = subv
                        temp_results.update({subt: framework.results.TestResult(subv)})

                        self.tests['all'].add(subt)
                        while subt != '':
                            fgh(subt, subv)
                            subt = grouptools.groupname(subt)
                        fgh('all', subv)

                    # remove the test from the 'all' list, this will cause to
                    # be treated as a group
                    self.tests['all'].discard(key)
                else:
                    # Walk the test name as if it was a path, at each level
                    # update the tests passed over the total number of tests
                    # (fractions), and update the status of the current level
                    # if the status of the previous level was worse, but is not
                    # skip
                    while key != '':
                        fgh(key, value.result)
                        key = grouptools.groupname(key)

                    # when we hit the root update the 'all' group and stop
                    fgh('all', value.result)

            # Update the the results.tests dictionary with the subtests so that
            # they are entered into the appropriate pages other than all.
            # Updating it in the loop will raise a RuntimeError
            for key, value in temp_results.iteritems():
                results.tests[key] = value

        # Create the lists of statuses like problems, regressions, fixes,
        # changes and skips
        for test in self.tests['all']:
            status = []
            for each in self.results:
                try:
                    status.append(each.tests[test].result)
                except KeyError:
                    status.append(so.NOTRUN)

            # Problems include: warn, dmesg-warn, fail, dmesg-fail, and crash.
            # Skip does not go on this page, it has the 'skipped' page
            if max(status) > so.PASS:
                self.tests['problems'].add(test)

            # Find all tests with a status of skip
            if so.SKIP in status:
                self.tests['skipped'].add(test)

            if so.INCOMPLETE in status:
                self.tests['incomplete'].add(test)

            # find fixes, regressions, and changes
            for i in xrange(len(status) - 1):
                first = status[i]
                last = status[i + 1]
                if first in [so.SKIP, so.NOTRUN] and \
                        last not in [so.SKIP, so.NOTRUN]:
                    self.tests['enabled'].add(test)
                    self.tests['changes'].add(test)
                elif last in [so.SKIP, so.NOTRUN] and \
                        first not in [so.SKIP, so.NOTRUN]:
                    self.tests['disabled'].add(test)
                    self.tests['changes'].add(test)
                elif first < last:
                    self.tests['regressions'].add(test)
                    self.tests['changes'].add(test)
                elif first > last:
                    self.tests['fixes'].add(test)
                    self.tests['changes'].add(test)

    def generate_html(self, destination, exclude):
        """
        Produce HTML summaries.

        Basically all this does is takes the information provided by the
        constructor, and passes it to mako templates to generate HTML files.
        The beauty of this approach is that mako is leveraged to do the
        heavy lifting, this method just passes it a bunch of dicts and lists
        of dicts, which mako turns into pretty HTML.
        """
        # Copy static files
        shutil.copy(path.join(self.TEMPLATE_DIR, "index.css"),
                    path.join(destination, "index.css"))
        shutil.copy(path.join(self.TEMPLATE_DIR, "result.css"),
                    path.join(destination, "result.css"))

        # Create the mako object for creating the test/index.html file
        testindex = Template(filename=path.join(self.TEMPLATE_DIR,
                                                "testrun_info.mako"),
                             output_encoding="utf-8",
                             encoding_errors='replace',
                             module_directory=self.TEMP_DIR)

        # Create the mako object for the individual result files
        testfile = Template(filename=path.join(self.TEMPLATE_DIR,
                                               "test_result.mako"),
                            output_encoding="utf-8",
                            encoding_errors='replace',
                            module_directory=self.TEMP_DIR)

        result_css = path.join(destination, "result.css")
        index = path.join(destination, "index.html")

        # Iterate across the tests creating the various test specific files
        for each in self.results:
            name = escape_pathname(each.name)
            try:
                os.mkdir(path.join(destination, name))
            except OSError as e:
                if e.errno == errno.EEXIST:
                    raise exceptions.PiglitFatalError(
                        'Two or more of your results have the same "name" '
                        'attribute. Try changing one or more of the "name" '
                        'values in your json files.\n'
                        'Duplicate value: {}'.format(name))
                else:
                    raise e

            if each.time_elapsed is not None:
                time = datetime.timedelta(0, each.time_elapsed)
            else:
                time = None

            with open(path.join(destination, name, "index.html"), 'w') as out:
                out.write(testindex.render(
                    name=each.name,
                    totals=each.totals['root'],
                    time=time,
                    options=each.options,
                    uname=each.uname,
                    glxinfo=each.glxinfo,
                    lspci=each.lspci))

            # Then build the individual test results
            for key, value in each.tests.iteritems():
                html_path = path.join(destination, name,
                                      escape_filename(key + ".html"))
                temp_path = path.dirname(html_path)

                if value.result not in exclude:
                    # os.makedirs is very annoying, it throws an OSError if
                    # the path requested already exists, so do this check to
                    # ensure that it doesn't
                    if not path.exists(temp_path):
                        os.makedirs(temp_path)

                    if value.time:
                        value.time = datetime.timedelta(0, value.time)

                    with open(html_path, 'w') as out:
                        out.write(testfile.render(
                            testname=key,
                            value=value,
                            css=path.relpath(result_css, temp_path),
                            index=path.relpath(index, temp_path)))

        # Finally build the root html files: index, regressions, etc
        index = Template(filename=path.join(self.TEMPLATE_DIR, "index.mako"),
                         output_encoding="utf-8",
                         encoding_errors='replace',
                         module_directory=self.TEMP_DIR)

        empty_status = Template(filename=path.join(self.TEMPLATE_DIR,
                                                   "empty_status.mako"),
                                output_encoding="utf-8",
                                encoding_errors='replace',
                                module_directory=self.TEMP_DIR)

        pages = frozenset(['changes', 'problems', 'skipped', 'fixes',
                           'regressions', 'enabled', 'disabled'])

        # Index.html is a bit of a special case since there is index, all, and
        # alltests, where the other pages all use the same name. ie,
        # changes.html, self.changes, and page=changes.
        with open(path.join(destination, "index.html"), 'w') as out:
            out.write(index.render(
                results=HTMLIndex(self, self.tests['all']),
                page='all',
                pages=pages,
                colnum=len(self.results),
                exclude=exclude))

        # Generate the rest of the pages
        for page in pages:
            with open(path.join(destination, page + '.html'), 'w') as out:
                # If there is information to display display it
                if self.tests[page]:
                    out.write(index.render(
                        results=HTMLIndex(self, self.tests[page]),
                        pages=pages,
                        page=page,
                        colnum=len(self.results),
                        exclude=exclude))
                # otherwise provide an empty page
                else:
                    out.write(empty_status.render(page=page, pages=pages))

    def generate_text(self, mode):
        """ Write summary information to the console """
        assert mode in ['summary', 'diff', 'incomplete', 'all'], mode

        def printer(list_):
            """Takes a list of test names to print and prints the name and
            result.

            """
            def make_status(test):
                elems = []
                for res in self.results:
                    try:
                        elems.append(str(res.tests[test].result))
                    except KeyError:
                        elems.append(str(so.NOTRUN))
                return ' '.join(elems)

            for test in list_:
                print("{test}: {statuses}".format(
                    test='/'.join(test.split(grouptools.SEPARATOR)),
                    statuses=make_status(test)))

        def print_summary():
            """print a summary."""
            template = textwrap.dedent("""\
                summary:
                       name: {names}
                       ----  {divider}
                       pass: {pass_}
                       fail: {fail}
                      crash: {crash}
                       skip: {skip}
                    timeout: {timeout}
                       warn: {warn}
                 incomplete: {incomplete}
                 dmesg-warn: {dmesg_warn}
                 dmesg-fail: {dmesg_fail}
                    changes: {changes}
                      fixes: {fixes}
                regressions: {regressions}
                      total: {total}""")

            def make(value):
                # This convaluted little function makes a formatter string that
                # looks like this: {: >x.x}, which prints a string that is x
                # characters wide and truncated at x, and right aligned, using
                # spaces to pad any remaining space on the left
                return '{: >' + '{0}.{0}'.format(value) + '}'

            lens = [max(min(len(x.name), 20), 6) for x in self.results]
            print_template = ' '.join(make(y) for y in lens)

            def status_printer(stat):
                totals = [str(x.totals['root'][stat]) for x in self.results]
                return print_template.format(*totals)

            def change_printer(func):
                counts = ['']  # There can't be changes from nil -> 0
                counts.extend([str(len(e)) for e in find_diffs(
                    self.results, self.tests['all'], func)])
                return print_template.format(*counts)

            print(template.format(
                names=print_template.format(*[r.name for r in self.results]),
                divider=print_template.format(*['-'*l for l in lens]),
                pass_=status_printer('pass'),
                crash=status_printer('crash'),
                fail=status_printer('fail'),
                skip=status_printer('skip'),
                timeout=status_printer('timeout'),
                warn=status_printer('warn'),
                incomplete=status_printer('incomplete'),
                dmesg_warn=status_printer('dmesg-warn'),
                dmesg_fail=status_printer('dmesg-fail'),
                changes=change_printer(operator.ne),
                fixes=change_printer(operator.gt),
                regressions=change_printer(operator.lt),
                total=print_template.format(*[
                    str(sum(x.totals['root'].itervalues()))
                    for x in self.results])))

        # Print the name of the test and the status from each test run
        if mode == 'all':
            printer(self.tests['all'])
            print_summary()
        elif mode == 'diff':
            printer(self.tests['changes'])
            print_summary()
        elif mode == 'incomplete':
            printer(self.tests['incomplete'])
        elif mode == 'summary':
            print_summary()


def find_diffs(results, tests, comparator):
    """Generate diffs between two or more sets of results."""
    diffs = []
    for prev, cur in itertools.izip(results[:-1], results[1:]):
        names = set()
        for name in tests:
            try:
                if comparator(prev.tests[name].result, cur.tests[name].result):
                    names.add(name)
            except KeyError:
                pass
        diffs.append(names)
    return diffs
