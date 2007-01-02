# jhbuild - a build script for GNOME 1.x and 2.x
# Copyright (C) 2001-2006  James Henstridge
#
#   svn.py: some code to handle various Subversion operations
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

__all__ = []
__metaclass__ = type

import os
import urlparse

from jhbuild.errors import CommandError, BuildStateError, FatalError
from jhbuild.utils.cmds import get_output
from jhbuild.versioncontrol import Repository, Branch, register_repo_type

# Make sure that the urlparse module considers svn:// and svn+ssh://
# schemes to be netloc aware and set to allow relative URIs.
if 'svn' not in urlparse.uses_netloc:
    urlparse.uses_netloc.append('svn')
if 'svn' not in urlparse.uses_relative:
    urlparse.uses_relative.append('svn')
if 'svn+ssh' not in urlparse.uses_netloc:
    urlparse.uses_netloc.append('svn+ssh')
if 'svn+ssh' not in urlparse.uses_relative:
    urlparse.uses_relative.append('svn+ssh')

def _make_uri(repo, path):
    if repo[-1] != '/':
        return '%s/%s' % (repo, path)
    else:
        return repo + path

def get_info(filename):
    # we run Subversion in the C locale, because Subversion localises
    # the key names in the output.  See bug #334678 for more info.
    output = get_output(
        ['svn', 'info', filename],
        extra_env={
            'LANGUAGE': 'C',
            'LC_ALL': 'C',
            'LANG': 'C'})
    ret = {}
    for line in output.splitlines():
        if ':' not in line: continue
        key, value = line.split(':', 1)
        ret[key.lower().strip()] = value.strip()
    return ret

def get_uri(filename):
    try:
        info = get_info(filename)
    except CommandError:
        raise BuildStateError('could not get Subversion URI for %s'
                              % filename)
    if 'url' not in info:
        raise BuildStateError('could not parse "svn info" output for %s'
                              % filename)
    return info['url']


class SubversionRepository(Repository):
    """A class used to work with a Subversion repository"""

    init_xml_attrs = ['href']

    def __init__(self, config, name, href):
        Repository.__init__(self, config, name)
        # allow user to adjust location of branch.
        self.href = config.repos.get(name, href)

    branch_xml_attrs = ['module', 'checkoutdir']

    def branch(self, name, module=None, checkoutdir=None):
        if module is None:
            module = name
            
        if module in self.config.branches and self.config.branches[module]:
            module = self.config.branches[module]
        else:
            module = urlparse.urljoin(self.href, module)

        trunk = module + "/trunk"
        for part in module.split('/'):
            if part in ['trunk', 'branches', 'tags', 'releases']:
                trunk = None
                break
        if not trunk is None:
            module = trunk
            checkoutdir = name
        
        return SubversionBranch(self, module, checkoutdir)


class SubversionBranch(Branch):
    """A class representing a Subversion branch"""

    def __init__(self, repository, module, checkoutdir):
        self.repository = repository
        self.config = repository.config
        self.module = module
        self.checkoutdir = checkoutdir

    def srcdir(self):
        if self.checkoutdir:
            return os.path.join(self.config.checkoutroot, self.checkoutdir)
        else:
            return os.path.join(self.config.checkoutroot,
                                os.path.basename(self.module))
    srcdir = property(srcdir)

    def branchname(self):
        # The convention for Subversion repositories is to put the head
        # branch under trunk/, branches under branches/foo/ and tags
        # under tags/bar/.
        # Use this to give a meaningful revision number.
        path_parts = self.module.split('/')
        for i, part in enumerate(path_parts):
            if part in ['branches', 'tags', 'releases']:
                return path_parts[i+1]
            elif part == 'trunk':
                break
        return None
    branchname = property(branchname)

    def _checkout(self, buildscript):
        cmd = ['svn', 'checkout', self.module]

        if self.checkoutdir:
            cmd.append(self.checkoutdir)

        if self.config.sticky_date:
            cmd.extend(['-r', '{%s}' % self.config.sticky_date])

        buildscript.execute(cmd, 'svn', cwd=self.config.checkoutroot)
    
    def _update(self, buildscript):
        opt = []
        if self.config.sticky_date:
            opt.extend(['-r', '{%s}' % self.config.sticky_date])

        # if the URI doesn't match, use "svn switch" instead of "svn update"
        if get_uri(self.srcdir) != self.module:
            cmd = ['svn', 'switch'] + opt + [self.module]
        else:
            cmd = ['svn', 'update'] + opt + ['.']

        buildscript.execute(cmd, 'svn', cwd=self.srcdir)

    def checkout(self, buildscript):
        if os.path.exists(self.srcdir):
            self._update(buildscript)
        else:
            self._checkout(buildscript)

    def force_checkout(self, buildscript):
        self._checkout(buildscript)

    def tree_id(self):
        if not os.path.exists(self.srcdir):
            return None
        info = get_info(self.srcdir)
        url = info['url']
        root = info['repository root']
        uuid = info['repository uuid']
        rev = info['last changed rev']

        # get the path within the repository
        assert url.startswith(root)
        path = url[len(root):]
        while path.startswith('/'):
            path = path[1:]

        return '%s,%s,%s' % (uuid.lower(), rev, path)


register_repo_type('svn', SubversionRepository)
