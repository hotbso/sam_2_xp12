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
    eps_pos = 0.00001
    eps_hdg = 1.0

    #<jetway name="Gate 11" latitude="49.495060845089135" longitude="11.077626914186194" heading="8.2729158401489258" 
    # height="4.33699989" wheelPos="9.35599995" cabinPos="17.6229992" cabinLength="2.84500003"
    # wheelDiameter="1.21200001" wheelDistance="1.79999995" sound="alarm2.ogg"
    # minRot1="-85" maxRot1="5" minRot2="-72" maxRot2="41" minRot3="-6" maxRot3="6"
    # minExtent="0" maxExtent="15.3999996" minWheels="-2" maxWheels="2"
    # initialRot1="-60.0690002" initialRot2="-37.8320007" initialRot3="-3.72300005" initialExtent="0" />
    jw_re = re.compile('.* latitude="([^"]+)".* longitude="([^"]+)".* heading="([^"]+)".* cabinPos="([^"]+)".* initialRot1="([^"]+)".* initialRot2="([^"]+)".*')

    def __init__(self, line):
        m = self.jw_re.match(line)
        if m is None:
            log.error(f"Cannot parse jetway line: '{line}'")

        self.lat = float(m.group(1))
        self.lon = float(m.group(2))
        self.hdg = float(m.group(3))
        self.length = float(m.group(4))
        self.jw_hdg = float(m.group(5))
        self.cab_hdg = float(m.group(6))

    def __repr__(self):
        return f"sam_jw {self.lat} {self.lon} {self.length} {self.jw_hdg} {self.cab_hdg}"

    def is_pos(self, obj_ref):
        return (abs(self.lat - obj_ref.lat) < self.eps_pos and
                abs(self.lon - obj_ref.lon) < self.eps_pos and
                abs(self.hdg - obj_ref.hdg) < self.eps_hdg)

class SAM():
    def __init__(self):
        self.jetways = []

        for l in open("sam.xml", "r").readlines():
            if l.find("<jetway name") > 0:
                self.jetways.append(SAM_jw(l))

    def match_jetways(self, obj_ref):
        for jw in self.jetways:
            if jw.is_pos(obj_ref):
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
    n_jw = 0
    n_docks = 0

    def __init__(self, fname):
        self.fname = fname.replace('\\', '/')   # src folder
        base, _ = os.path.splitext(self.fname) # dst folder
        self.dsf_base = base.replace("Earth nav data.pre_s2n", "Earth nav data")

    def __repr__(self):
        return f"{self.fname}"

    def run_cmd(self, cmd):
        # "shell = True" is not needed on Windows, bombs on Lx
        out = subprocess.run(shlex.split(cmd), capture_output = True)
        if out.returncode != 0:
            log.error(f"Can't run {cmd}: {out}")
            sys.exit(2)

    def parse(self):
        obj_id = 0
        dsf_txt = self.dsf_base + ".txt_pre"

        self.run_cmd(f'"{dsf_tool}" -dsf2text "{self.fname}" "{dsf_txt}"')

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
            if sam.match_jetways(o):
                o.is_jetway = True
                self.object_defs[o.id].is_jetway = True
                self.n_jw += 1

    def write(self):
        dsf_txt = self.dsf_base + ".txt"
        with open(dsf_txt, "w") as f:
            for section in [self.before_obj_defs, self.object_defs,
                            self. before_obj_refs, self.object_refs, self.rest]:
                for o in section:
                    f.write(f"{o}\n")

        self.run_cmd(f'"{dsf_tool}" -text2dsf "{dsf_txt}" "{self.dsf_base}.dsf"')


###########
## main
###########
logging.basicConfig(level=logging.INFO,
                    handlers=[logging.FileHandler(filename = "sam_2_native.log", mode='w'),
                              logging.StreamHandler()])

log.info(f"Version: {VERSION}")
log.info(f"args: {sys.argv}")

CFG = configparser.ConfigParser()
CFG.read('sam_2_native.ini')
dry_run = False

def usage():
    log.error( \
        """sam_2_native [-rect lower_left,upper_right] [-subset string] [-limit n] [-dry_run] [-root xp12_root] convert|undo|cleanup
            -dry_run    only list matching files

        """)
    sys.exit(2)

mode = None

i = 1
while i < len(sys.argv):
    if sys.argv[i] == "-dry_run":
        dry_run = True

    i = i + 1

# if mode is None:
    # usage()

dsf_tool = CFG['TOOLS']['dsftool']

sanity_checks = True
if not os.path.isfile(dsf_tool):
    sanity_checks = False
    log.error(f"dsf_tool: '{dsf_tool}' is not pointing to a file")

if not os.path.isdir("Earth nav data"):
    sanity_checks = False
    log.error(f'No "Earth nav data" folder found')

if not os.path.isfile("Earth nav data/apt.dat"):
    sanity_checks = False
    log.error(f'No "Earth nav data/apt.dat" file found')

if not sanity_checks:
    sys.exit(2)

log.info(f"dsf_tool:  {dsf_tool}")

src_dir = "Earth nav data.pre_s2n"
if not os.path.isdir(src_dir):
    src_dir = shutil.copytree("Earth nav data", "Earth nav data.pre_s2n")
    log.info(f'Created backup copy "{src_dir}"')

sam = SAM()

dsf_list = []
for dir, dirs, files in os.walk(src_dir):
    for f in files:
        _, ext = os.path.splitext(f)
        if ext != '.dsf':
            continue

        full_name = os.path.join(dir, f)
        dsf = Dsf(full_name)
        dsf.parse()
        dsf_list.append(dsf)

print("SAM jetways")
for jw in sam.jetways:
    print(jw)

for dsf in dsf_list:
    dsf.filter_jetways(sam)
    if dsf.n_jw > 0:
        print(f"\nOBJECT_DEFs that are jetways in {dsf.fname}")
        for o in dsf.object_defs:
            if o.is_jetway:
                print(o)

        print(f"\nOBJECTs that are jetways in {dsf.fname}")
        for o in dsf.object_refs:
            if o.is_jetway:
                print(o)

        dsf.write()
