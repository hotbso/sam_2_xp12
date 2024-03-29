# MIT License

# Copyright (c) 2024 Holger Teutsch

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

VERSION = "1"

import platform, sys, os, os.path, time, shlex, subprocess, shutil, re

import configparser
import logging

log = logging.getLogger("sam_2_native")

class SAM_jw():
    eps = 0.00001

    def __init__(self, lat, lon, length, jw_hdg, cab_hdg):
        self.lat = lat
        self.lon = lon
        self.length = length
        self.jw_hdg = jw_hdg
        self.cab_hdg = cab_hdg

    def __repr__(self):
        return f"sam_jw {self.lat} {self.lon} {self.length} {self.jw_hdg} {self.cab_hdg}"

    def is_pos(self, lat, lon):
        return abs(self.lat - lat) < self.eps and abs(self.lon - lon) < self.eps

class SAM():
    def __init__(self):
        self.jetways = []

        #<jetway name="Gate 11" latitude="49.495060845089135" longitude="11.077626914186194" heading="8.2729158401489258" height="4.33699989" wheelPos="9.35599995" cabinPos="17.6229992" cabinLength="2.84500003" wheelDiameter="1.21200001" wheelDistance="1.79999995" sound="alarm2.ogg" minRot1="-85" maxRot1="5" minRot2="-72" maxRot2="41" minRot3="-6" maxRot3="6" minExtent="0" maxExtent="15.3999996" minWheels="-2" maxWheels="2" initialRot1="-60.0690002" initialRot2="-37.8320007" initialRot3="-3.72300005" initialExtent="0" />

        jw_re = re.compile('.*jetway name=.* latitude="([^"]+)".* longitude="([^"]+)".* heading="([^"]+)".* cabinPos="([^"]+)".* initialRot1="([^"]+)".* initialRot2="([^"]+)".*')
        #jw_re = re.compile('.*jetway name=.* latitude="')
        for l in open("sam.xml", "r").readlines():
            m = jw_re.match(l)
            if m:
                #print(l)
                lat = float(m.group(1))
                lon = float(m.group(2))
                length = float(m.group(4))
                jw_hdg = float(m.group(5))
                cab_hdg = float(m.group(6))
                self.jetways.append(SAM_jw(lat, lon, length, jw_hdg, cab_hdg))

    def match_jetways(self, lat, lon):
        for jw in self.jetways:
            if jw.is_pos(lat, lon):
                return True

        return False

class ObjectRef():
    is_jetway = False

    def __init__(self, id, lat, lon, hdg):
        self.id = id
        self.lat = lat
        self.lon = lon
        self.hdg = hdg

    def __repr__(self):
        return f"OBJECT {self.id} {self.lon} {self.lat} {self.hdg}"

class ObjectDef():
    is_jetway = False

    def __init__(self, id, name):
        self.id = id
        self.name = name

    def __repr__(self):
        return f"OBJECT_DEF {self.name}"

class Dsf():

    def __init__(self, fname):
        self.fname = fname.replace('\\', '/')
        self.fname_bck = self.fname + "-pre_sam_2_native"
        self.cnv_marker = self.fname + "-sam_2_native_done"
        self.dsf_base, _ = os.path.splitext(os.path.basename(self.fname))
        self.rdata = []
        self.is_converted = os.path.isfile(self.cnv_marker)
        self.has_backup = os.path.isfile(self.fname_bck)

    def __repr__(self):
        return f"{self.fname}"

    def run_cmd(self, cmd):
        # "shell = True" is not needed on Windows, bombs on Lx
        out = subprocess.run(shlex.split(cmd), capture_output = True)
        if out.returncode != 0:
            log.error(f"Can't run {cmd}: {out}")
            return False

        return True

    def parse(self):
        i = self.fname.find("/Earth nav data/")
        assert i > 0, "invalid filename"

        obj_id = 0
        dsf_txt = self.dsf_base + ".txt"

        if not self.run_cmd(f'"{dsf_tool}" -dsf2text "{self.fname}" "{dsf_txt}"'):
            return False

        dsf_txt_lines = open(dsf_txt, "r").readlines()
        self.before_obj_defs = []
        self.object_defs = []
        self.before_obj_refs = []
        self.object_refs = []
        self.rest = []
        active = self.before_obj_defs

        for l in dsf_txt_lines:
            l = l.rstrip()
            if len(l) == 0 or l[0] == "#":
                continue

            #print(l)
            words = l.split()
            if len(words) > 0 and words[0] == "OBJECT_DEF":
                self.object_defs.append(ObjectDef(obj_id, words[1]))
                obj_id += 1
                active = self.before_obj_refs
                continue

            if len(words) > 0 and words[0] == "OBJECT":
                self.object_refs.append(ObjectRef(int(words[1]), float(words[3]), float(words[2]), float(words[4])))
                active = self.rest
                continue


            active.append(l)

        if False:
            for i in range(len(object_defs)):
                print(f"{i} {self.object_defs[i]}")

            for o_r in self.object_refs:
                print(o_r)

        # # always create a backup
        # if not os.path.isfile(self.fname_bck):
            # shutil.copy2(self.fname, self.fname_bck)

        # fname_new = self.fname + "-new"
        # fname_new_1 = fname_new + "-1"
        # tmp_files.append(fname_new_1)
        # if not self.run_cmd(f'"{dsf_tool}" -text2dsf "{o4xp_dsf_txt}" "{fname_new_1}"'):
            # return False

        # if not self.run_cmd(f'"{cmd_7zip}" a -t7z -m0=lzma "{fname_new}" "{fname_new_1}"'):
            # return False

        # os.remove(self.fname)
        # os.rename(fname_new, self.fname)
        # open(self.cnv_marker, "w")  # create the marker
        return True

    def filter_jetways(self, sam):
        for o in self.object_refs:
            if sam.match_jetways(o.lat, o.lon):
                o.is_jetway = True
                self.object_defs[o.id].is_jetway = True

    def write(self):
        with open("new.txt", "w") as f:
            for section in [self.before_obj_defs, self.object_defs,
                            self. before_obj_refs, self.object_refs, self.rest]:
                for o in section:
                    f.write(f"{o}\n")

            # for l in self.before_obj_defs:
                # f.write(f"{l)
            # for o in self.object_defs:
                # f.write(f"{o}")
            # for l in self.before_obj_refs:
                # f.write(l)
            # for o in self.object_refs:
                # f.write(f"{o}")
            # for l in self.rest:
                # f.write(l)

    # def undo(self):
        # os.remove(self.fname)
        # os.rename(self.fname_bck, self.fname)
        # try:
            # os.remove(self.cnv_marker)
        # except:
            # pass

    # def cleanup(self):
        # os.remove(self.fname_bck)


###########
## main
###########
logging.basicConfig(level=logging.INFO,
                    handlers=[logging.FileHandler(filename = "o4x_2_xp12.log", mode='w'),
                              logging.StreamHandler()])

log.info(f"Version: {VERSION}")
log.info(f"args: {sys.argv}")

CFG = configparser.ConfigParser()
CFG.read('sam_2_native.ini')
dry_run = False

def usage():
    log.error( \
        """sam_2_native [-rect lower_left,upper_right] [-subset string] [-limit n] [-dry_run] [-root xp12_root] convert|undo|cleanup
            -rect       restrict to rectangle, corners format is lat,lon, e.g. +50+009
            -subset     matching filenames must contain the string
            -dry_run    only list matching files
            -root       override root
            -limit n    limit operation to n dsf files

            convert     you guessed it
            undo        undo conversions
            cleanup     remove backup files

            convert, undo, cleanup are mutually exclusive

            Examples:
                sam_2_native -rect +36+019,+40+025 convert
                sam_2_native -subset z_ao_eur -dry_run cleanup
                sam_2_native -root E:/XP12-test -subset z_ao_eur -limit 1000 convert
                sam_2_native -rect +36+019,+40+025 -cleanup
        """)
    sys.exit(2)

mode = None

i = 1
while i < len(sys.argv):
    if sys.argv[i] == "-dry_run":
        dry_run = True

    elif sys.argv[i] == "convert":
        if mode is not None:
            usage()
        mode = DsfList.M_CONVERT

    elif sys.argv[i] == "redo":
        if mode is not None:
            usage()
        mode = DsfList.M_REDO

    elif sys.argv[i] == "undo":
        if mode is not None:
            usage()
        mode = DsfList.M_UNDO

    elif sys.argv[i] == "cleanup":
        if mode is not None:
            usage()
        mode = DsfList.M_CLEANUP

    else:
        usage()

    i = i + 1

# if mode is None:
    # usage()

dsf_tool = CFG['TOOLS']['dsftool']

sanity_checks = True
if not os.path.isfile(dsf_tool):
    sanity_checks = False
    log.error(f"dsf_tool: '{dsf_tool}' is not pointing to a file")


if not sanity_checks:
    sys.exit(2)

log.info(f"dsf_tool:  {dsf_tool}")

sam = SAM()

dsf = Dsf("./Earth nav data/+40+010/+49+011.dsf")
dsf.parse()

print("SAM jetways")
for jw in sam.jetways:
    print(jw)

dsf.filter_jetways(sam)

print("\nOBJECT_DEFs that are jetways")
for o in dsf.object_defs:
    if o.is_jetway:
        print(o)

print("\nOBJECTs that are jetways")
for o in dsf.object_refs:
    if o.is_jetway:
        print(o)

dsf.write()