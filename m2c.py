#! /usr/bin/python

import os
import sys

import gzip

import yaml

# import yum
import rpm
import stat
# import rpmUtils
# check if rpm has the new weakdeps tags
_rpm_has_new_weakdeps = hasattr(rpm, 'RPMTAG_ENHANCENAME')

modmd_only = False
build_rpm = True

if len(sys.argv) < 4:
    print >>sys.stderr, " Args: <Combined modmd> <rpmdir> <outdir>"
    sys.exit(1)

modmd  = sys.argv[1]
rpmdir = sys.argv[2]
outdir = sys.argv[3]

if modmd.endswith(".gz"):
    modmd = gzip.open(modmd)
else:
    modmd = open(mdmd)

if outdir[0] != '/':
    outdir = os.getcwd() + '/' + outdir

if not os.path.exists(outdir):
    os.makedirs(outdir)

def version_tuple_to_string(evrTuple):
    """
    Convert a tuple representing a package version to a string.

    @param evrTuple: A 3-tuple of epoch, version, and release.

    Return the string representation of evrTuple.
    """
    (e, v, r) = evrTuple
    s = ""
    
    if e not in [0, '0', None]:
        s += '%s:' % e
    if v is not None:
        s += '%s' % v
    if r is not None:
        s += '-%s' % r
    return s

def prco_tuple_to_string(prcoTuple):
    """returns a text string of the prco from the tuple format"""

    (name, flag, evr) = prcoTuple
    flags = {'GT':'>', 'GE':'>=', 'EQ':'=', 'LT':'<', 'LE':'<='}
    if flag is None:
        return name

    return '%s %s %s' % (name, flags[flag], version_tuple_to_string(evr))

def nevra_split(nevra):
    """Take a full nevra string and return a tuple. """
    n, ev, ra = nevra.rsplit('-', 2)
    if ':' in ev:
        e, v = ev.split(':', 1)
    else:
        e, v = ev, '0'
    r, a = ra.rsplit('.', 1)
    return n, e, v, r, a

def re_primary_filename(filename):
    """ Tests if a filename string, can be matched against just primary.
        Note that this can produce false negatives (Eg. /b?n/zsh) but not false
        positives (because the former is a perf hit, and the later is a
        failure). Note that this is a superset of re_primary_dirname(). """
    if re_primary_dirname(filename):
        return True
    if filename == '/usr/lib/sendmail':
        return True
    return False

def re_primary_dirname(dirname):
    """ Tests if a dirname string, can be matched against just primary. Note
        that this is a subset of re_primary_filename(). """
    if 'bin/' in dirname:
        return True
    if dirname.startswith('/etc/'):
        return True
    return False

def initReadOnlyTransaction(root='/'):
    read_ts = rpm.TransactionSet(root)
    read_ts.setVSFlags((rpm._RPMVSF_NOSIGNATURES|rpm._RPMVSF_NODIGESTS))
    return read_ts

def hdrFromPackage(ts, package):
    """hand back the rpm header or raise an Error if the pkg is fubar"""
    try:
        fdno = os.open(package, os.O_RDONLY)
    except OSError, e:
        raise

    # XXX: We should start a readonly ts here, so we don't get the options
    # from the other one (sig checking, etc)
    try:
        hdr = ts.hdrFromFdno(fdno)
    except rpm.error, e:
        os.close(fdno)
        raise ValueError, "RPM Error opening Package"
    if type(hdr) != rpm.hdr:
        os.close(fdno)
        raise ValueError, "RPM Error opening Package (type)"

    os.close(fdno)
    return hdr

def flagToString(flags):
    flags = flags & 0xf

    if flags == 0: return None
    elif flags == 2: return 'LT'
    elif flags == 4: return 'GT'
    elif flags == 8: return 'EQ'
    elif flags == 10: return 'LE'
    elif flags == 12: return 'GE'

    return flags

def stringToVersion(verstring):
    if verstring in [None, '']:
        return (None, None, None)
    i = verstring.find(':')
    if i != -1:
        try:
            epoch = str(long(verstring[:i]))
        except ValueError:
            # look, garbage in the epoch field, how fun, kill it
            epoch = '0' # this is our fallback, deal
    else:
        epoch = '0'
    j = verstring.find('-')
    if j != -1:
        if verstring[i + 1:j] == '':
            version = None
        else:
            version = verstring[i + 1:j]
        release = verstring[j + 1:]
    else:
        if verstring[i + 1:] == '':
            version = None
        else:
            version = verstring[i + 1:]
        release = None
    return (epoch, version, release)

def comparePoEVR(po1, po2):
    """
    Compare two Package or PackageEVR objects.
    """
    (e1, v1, r1) = (po1.epoch, po1.version, po1.release)
    (e2, v2, r2) = (po2.epoch, po2.version, po2.release)
    return rpm.labelCompare((e1, v1, r1), (e2, v2, r2))

# HACK: This is completely retarded. Don't blame me, someone just fix
#       rpm-python already. This is almost certainly not all of the problems,
#       but w/e.
def _rpm_long_size_hack(hdr, size):
    """ Rpm returns None, for certain sizes. And has a "longsize" for the real
        values. """
    return hdr[size] or hdr['long' + size]

class cpkg(object):
    def __init__(self, filename):
        ts = initReadOnlyTransaction()
        hdr = hdrFromPackage(ts, filename)
        self.hdr = hdr
        self.epoch = self.doepoch()
        self.ver = self.version
        self.rel = self.release
        self.pkgtup = (self.name, self.arch, self.epoch, self.ver, self.rel)

        self.pkgid = self.hdr[rpm.RPMTAG_SHA1HEADER]
        if not self.pkgid:
            self.pkgid = "%s.%s" %(self.hdr['name'], self.hdr['buildtime'])
        self.packagesize = _rpm_long_size_hack(self.hdr, 'archivesize')
        self.installedsize = _rpm_long_size_hack(self.hdr, 'size')

        self.__mode_cache = {}
        self.__prcoPopulated = False
        self._loadedfiles = False
        self.prco = {}
        self.prco['obsoletes'] = [] # (name, flag, (e,v,r))
        self.prco['conflicts'] = [] # (name, flag, (e,v,r))
        self.prco['requires'] = [] # (name, flag, (e,v,r))
        self.prco['provides'] = [] # (name, flag, (e,v,r))
        self.prco['suggests'] = [] # (name, flag, (e,v,r))
        self.prco['enhances'] = [] # (name, flag, (e,v,r))
        self.prco['recommends'] = [] # (name, flag, (e,v,r))
        self.prco['supplements'] = [] # (name, flag, (e,v,r))
        self.files = {}
        self.files['file'] = []
        self.files['dir'] = []
        self.files['ghost'] = []


    def __getattr__(self, thing):
        #FIXME - if an error - return AttributeError, not KeyError 
        # ONLY FIX THIS AFTER THE API BREAK
        if thing.startswith('__') and thing.endswith('__'):
            # If these existed, then we wouldn't get here ...
            # So these are missing.
            raise AttributeError, "%s has no attribute %s" % (self, thing)
        try:
            return self.hdr[thing]
        except KeyError:
            #  Note above, API break to fix this ... this at least is a nicer
            # msg. so we know what we accessed that is bad.
            raise KeyError, "%s has no attribute %s" % (self, thing)
        except ValueError:
            #  Note above, API break to fix this ... this at least is a nicer
            # msg. so we know what we accessed that is bad.
            raise ValueError, "%s has no attribute %s" % (self, thing)

    def __str__(self):
        if self.epoch == '0':
            val = '%s-%s-%s.%s' % (self.name, self.version, self.release,
                                        self.arch)
        else:
            val = '%s-%s:%s-%s.%s' % (self.name, self.epoch, self.version,
                                           self.release, self.arch)
        return val

    def verCMP(self, other):
        """ Compare package to another one, only rpm-version ordering. """
        if not other:
            return 1
        ret = cmp(self.name, other.name)
        if ret == 0:
            ret = comparePoEVR(self, other)
        return ret

    def __cmp__(self, other):
        """ Compare packages, this is just for UI/consistency. """
        ret = self.verCMP(other)
        if ret == 0:
            ret = cmp(self.arch, other.arch)
        return ret

    def _size(self):
        return _rpm_long_size_hack(self.hdr, 'size')

    size     = property(fget=lambda x: x._size)

    def doepoch(self):
        tmpepoch = self.hdr['epoch']
        if tmpepoch is None:
            epoch = '0'
        else:
            epoch = str(tmpepoch)

        return epoch

    def _returnPrco(self, prcotype, printable=False):
        """return list of provides, requires, conflicts or obsoletes"""

        prcotype = {"weak_requires" : "recommends",
                    "info_requires" : "suggests",
                    "weak_reverse_requires" : "supplements",
                    "info_reverse_requires" : "enhances"}.get(prcotype,prcotype)
        prcos = self.prco.get(prcotype, [])

        if printable:
            results = []
            for prco in prcos:
                if not prco[0]: # empty or none or whatever, doesn't matter
                    continue
                results.append(prco_tuple_to_string(prco))
            return results

        return prcos

    def returnPrco(self, prcotype, printable=False):
        if not self.__prcoPopulated:
            self._populatePrco()
            self.__prcoPopulated = True
        return self._returnPrco(prcotype, printable)

    def _populatePrco(self):
        "Populate the package object with the needed PRCO interface."

        tag2prco = { "OBSOLETE": "obsoletes",
                     "CONFLICT": "conflicts",
                     "REQUIRE":  "requires",
                     "PROVIDE":  "provides" }

        def _end_nfv(name, flag, vers):
            flag = map(flagToString, flag)

            vers = map(stringToVersion, vers)
            vers = map(lambda x: (x[0], x[1], x[2]), vers)

            return zip(name,flag,vers)

        hdr = self.hdr
        for tag in tag2prco:
            name = hdr[getattr(rpm, 'RPMTAG_%sNAME' % tag)]
            if not name: # empty or none or whatever, doesn't matter
                continue

            lst = hdr[getattr(rpm, 'RPMTAG_%sFLAGS' % tag)]
            if tag == 'REQUIRE':
                #  Rpm is a bit magic here, and if pkgA requires(pre/post): foo
                # it will then let you remove foo _after_ pkgA has been
                # installed. So we need to mark those deps. as "weak".
                #  This is not the same as recommends/weak_requires.
                bits = rpm.RPMSENSE_SCRIPT_PRE | rpm.RPMSENSE_SCRIPT_POST
                weakreqs = [bool(flag & bits) for flag in lst]

            vers = hdr[getattr(rpm, 'RPMTAG_%sVERSION' % tag)]
            prcotype = tag2prco[tag]
            self.prco[prcotype] = _end_nfv(name, lst, vers)
            if tag == 'REQUIRE':
                weakreqs = zip(weakreqs, self.prco[prcotype])
                strongreqs = [wreq[1] for wreq in weakreqs if not wreq[0]]
                self.prco['strong_requires'] = strongreqs

        # This looks horrific as we are supporting both the old and new formats:
        tag2prco = { "SUGGEST":    ( "suggests",
                                     1156, 1157, 1158, 1 << 27, 0),
                     "ENHANCE":    ( "enhances",
                                     1159, 1160, 1161, 1 << 27, 0),
                     "RECOMMEND":  ( "recommends",
                                     1156, 1157, 1158, 1 << 27, 1 << 27),
                     "SUPPLEMENT": ( "supplements",
                                     1159, 1160, 1161, 1 << 27, 1 << 27) }
        for tag in tag2prco:
            (prcotype, oldtagn, oldtagv, oldtagf, andmask, resmask) = tag2prco[tag]
            name = None
            if _rpm_has_new_weakdeps:
                name = hdr[getattr(rpm, 'RPMTAG_%sNAME' % tag)]
            if not name:
                name = hdr[oldtagn]
                if not name:
                    continue
                (name, flag, vers) = self._filter_deps(name, hdr[oldtagf], hdr[oldtagv], andmask, resmask)
            else:
                flag = hdr[getattr(rpm, 'RPMTAG_%sFLAGS' % tag)]
                vers = hdr[getattr(rpm, 'RPMTAG_%sVERSION' % tag)]
            if not name: # empty or none or whatever, doesn't matter
                continue
            self.prco[prcotype] = _end_nfv(name, flag, vers)

    def _loadFiles(self):
        files = self.hdr['filenames']
        fileflags = self.hdr['fileflags']
        filemodes = self.hdr['filemodes']
        filetuple = zip(files, filemodes, fileflags)
        if not self._loadedfiles:
            for (fn, mode, flag) in filetuple:
                #garbage checks
                if mode is None or mode == '':
                    if 'file' not in self.files:
                        self.files['file'] = []
                    self.files['file'].append(fn)
                    continue
                if mode not in self.__mode_cache:
                    self.__mode_cache[mode] = stat.S_ISDIR(mode)

                fkey = 'file'
                if self.__mode_cache[mode]:
                    fkey = 'dir'
                elif flag is not None and (flag & 64):
                    fkey = 'ghost'
                self.files.setdefault(fkey, []).append(fn)

            self._loadedfiles = True

    def _returnFileEntries(self, ftype='file', primary_only=False):
        """return list of files based on type, you can pass primary_only=True
           to limit to those files in the primary repodata"""
        if self.files:
            if ftype in self.files:
                if primary_only:
                    if ftype == 'dir':
                        match = re_primary_dirname
                    else:
                        match = re_primary_filename
                    return [fn for fn in self.files[ftype] if match(fn)]
                return self.files[ftype]
        return []

    def returnFileEntries(self, ftype='file', primary_only=False):
        """return list of files based on type"""
        self._loadFiles()
        return self._returnFileEntries(ftype,primary_only)


# cpkg = yum.packages.YumLocalPackage
modmd = list(yaml.load_all(modmd))
for mod in modmd:
    mn = mod['data']['name'] + '-' + mod['data']['stream']
    print '=' * 79
    print ' ' * 30, mn
    print '-' * 79
    if 'api' in mod['data']:
        api = mod['data']['api']
        api['rpms'] = [mn + '-' + n for n in api['rpms']]

    artifacts = mod['data']['artifacts']
    nevras = artifacts['rpms'] # Need old ones for below...
    artifacts['rpms'] = [mn + '-' + n for n in artifacts['rpms']]

    if 'profiles' in mod['data']:
        for profile in mod['data']['profiles']:
            profile = mod['data']['profiles'][profile]
            profile['rpms'] = [mn + '-' + n for n in profile['rpms']]

    if modmd_only:
        nevras = []

    pkgs = []
    for nevra in nevras:
        print "Loading:", nevra
        n,e,v,r,a = nevra_split(nevra)
        if a == 'src': continue
        rpm_fname = "%s-%s-%s.%s.rpm" % (n, v, r, a)
        filename = rpmdir + '/' + rpm_fname
        if not os.path.exists(filename):
            filename = rpmdir + '/' + n[0] + '/' + rpm_fname
        if not os.path.exists(filename):
            print >>sys.stderr, " Warning: RPM NOT FOUND:", rpm_fname
            continue
        pkg = cpkg(filename=filename)
        pkgs.append(pkg)

    # Allowed prco data has to be within module:
    modprovs = set()
    for pkg in pkgs:
        for (n, f, (e, v, r)) in pkg.returnPrco('provides'):
            modprovs.add(n)

    for pkg in sorted(pkgs):
        print "Rebuilding:", pkg
        n, a, e, v, r = pkg.pkgtup
        rpm_fname = "%s-%s-%s.%s.rpm" % (n, v, r, a)
        filename = rpmdir + '/' + rpm_fname
        if not os.path.exists(filename):
            filename = rpmdir + '/' + n[0] + '/' + rpm_fname

        nn = mn + '-' + pkg.name

        os.system("rpm2cpio " + filename + " > " + nn + "-built.cpio")
        os.system("tar -cf " + nn + ".tar " + nn + "-built.cpio")
        os.remove(nn + "-built.cpio")
        os.system("gzip -f -9 " + nn + ".tar")

        spec = open(nn + ".spec", "w")
        noarch = ''
        if a == 'noarch':
            noarch = "BuildArch: noarch"

        provides, requires, conflicts, obsoletes = '', '', '', ''
        # FIXME: weak-requires/info-requires dito enhances BS.
        for data in pkg.returnPrco('provides'):
            if data[0] not in modprovs:
                continue
            data = prco_tuple_to_string(data)
            provides += 'Provides: %s-%s\n' % (mn, data)

        for data in pkg.returnPrco('requires'):
            if data[0] not in modprovs:
                continue
            data = prco_tuple_to_string(data)
            requires += 'Requires: %s-%s\n' % (mn, data)

        for data in pkg.returnPrco('conflicts'):
            if data[0] not in modprovs:
                continue
            data = prco_tuple_to_string(data)
            conflicts += 'Conflicts: %s-%s\n' % (mn, data)
        # FIXME: obs. wtf

        scriptlet = {}

        for sname, tname in (("pre", "prein"), ("preun", None),
                             ("post", "postin"), ("postun", None),
                             ("pretrans", None), ("posttrans", None)):
            if tname is None:
                tname = sname
            scriptlet[sname] = ''
            prog = getattr(pkg, tname + "prog")
            if not prog:
                continue
            assert len(prog) == 1
            prog = prog[0]
            scriptlet[sname] = """\
%%%s -p %s
%s
""" % (sname, prog, getattr(pkg, tname) or '')
        # FIXME: preinflags etc.

        filelist = \
        "\n".join(pkg.returnFileEntries('file')).replace(" ", "?") + "\n"
        # FIXME: other files, and attr
        # "\n".join(pkg.files['ghost']) +
        # "\n".join(pkg.files['dir']) +

        print >>spec, """\

%%define _sourcedir %s
%%define _srcrpmdir %s
%%define _rpmdir %s

%%define __os_install_post :
%%define __spec_install_post :

%%global __requires_exclude_from ^.*$
%%global __provides_exclude_from ^.*$
%%global __requires_exclude ^.*$
%%global __provides_exclude ^.*$

Name:       %s
Epoch:      %s
Version:    %s
Release:    %s
Summary:    %s

License:    %s
URL:        %s

# Provides/Requires/Conflicts/Obsoletes ... Namespaced:
%s
%s
%s
%s

BuildRequires: cpio
%s

Source0: %%{name}.tar.gz

%%description
%s

# Scriptlets...
%s
%s
%s
%s
%s
%s

%%prep
%%setup -c -q

%%install
mkdir -p $RPM_BUILD_ROOT
cp -a %%{name}-built.cpio $RPM_BUILD_ROOT
cd $RPM_BUILD_ROOT
cpio -dium < %%{name}-built.cpio
rm %%{name}-built.cpio

%%files
%s

""" % (os.getcwd(), outdir, outdir, nn, 
       pkg.epoch, pkg.version, pkg.release,
       pkg.summary, pkg.license, pkg.url,
       provides, requires, conflicts, obsoletes,
       noarch, pkg.description,
       scriptlet['pre'], scriptlet['preun'],
       scriptlet['post'], scriptlet['postun'],
       scriptlet['pretrans'], scriptlet['posttrans'],
       filelist)
        spec.close()

        if build_rpm:
            os.system("rpmbuild -bb " + nn + ".spec --quiet > /dev/null")
        else:
            os.system("rpmbuild -bs " + nn + ".spec --quiet > /dev/null")

        os.remove(nn + ".spec")
        os.remove(nn + ".tar.gz")

fo = open(outdir + '/' + 'modmd', 'w')
print >>fo, yaml.dump_all(modmd, explicit_start=True)
