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

import platform, sys, os, os.path, math, shlex, subprocess, shutil, re

import configparser
import logging

log = logging.getLogger("sam_2_native")

def normalize_hdg(hdg):
    hdg = math.fmod(hdg, 360.0)
    if hdg < 0:
        hdg += 360.0
    return hdg

class ObjPos():
    eps_pos = 0.00001
    eps_hdg = 1.0

    lat = None
    lon = None
    hdg = None

    def is_pos(self, obj_pos):
        return (abs(self.lat - obj_pos.lat) < self.eps_pos and
                abs(self.lon - obj_pos.lon) < self.eps_pos and
                abs(self.hdg - obj_pos.hdg) < self.eps_hdg)

class SAM_jw(ObjPos):

    #<jetway name="Gate 11" latitude="49.495060845089135" longitude="11.077626914186194" heading="8.2729158401489258"
    # height="4.33699989" wheelPos="9.35599995" cabinPos="17.6229992" cabinLength="2.84500003"
    # wheelDiameter="1.21200001" wheelDistance="1.79999995" sound="alarm2.ogg"
    # minRot1="-85" maxRot1="5" minRot2="-72" maxRot2="41" minRot3="-6" maxRot3="6"
    # minExtent="0" maxExtent="15.3999996" minWheels="-2" maxWheels="2"
    # initialRot1="-60.0690002" initialRot2="-37.8320007" initialRot3="-3.72300005" initialExtent="0" />
    jw_re = re.compile('.* latitude="([^"]+)".* longitude="([^"]+)".* heading="([^"]+)"' +
                       '.* cabinPos="([^"]+)".* maxExtent="([^"]+)"' +
                       '.* initialRot1="([^"]+)".* initialRot2="([^"]+)".*')

    def __init__(self, line):
        m = self.jw_re.match(line)
        if m is None:
            log.error(f"Cannot parse jetway line: '{line}'")

        self.lat = float(m.group(1))
        self.lon = float(m.group(2))
        self.hdg = float(m.group(3))
        self.length = float(m.group(4))
        self.max_extend = float(m.group(5))
        self.jw_hdg = float(m.group(6))
        self.cab_hdg = float(m.group(7))

    def __repr__(self):
        return f"sam_jw {self.lat} {self.lon} {self.length}m {self.max_extend}m {self.jw_hdg}° {self.cab_hdg}°"

    def apt_1500(self):
        total_length = self.length + self.max_extend
        lcode = -1
        if self.length >= 11 and self.length <= 23:
            lcode = 0
        if self.length >= 14 and self.length <= 29:
            lcode = 1
        if self.length >= 17 and self.length <= 38:
            lcode = 2
        if self.length >= 20 and self.length <= 47:
            lcode = 3

        if lcode < 0:
            log.error(f"can't find tunnel for {self}")
            sys.exit(2)

        jw_hdg = normalize_hdg(self.jw_hdg)
        cab_hdg = normalize_hdg(self.jw_hdg + self.cab_hdg)

        return f"1500 {self.lat:0.8f} {self.lon:0.8f} {jw_hdg:0.1f} 2 {lcode} 0 {self.length:0.1f} {cab_hdg:0.1f}"

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

class ObjectRef(ObjPos):
    is_jetway = False

    def __init__(self, id, lat, lon, hdg):
        self.id = id
        self.lat = lat
        self.lon = lon
        self.hdg = hdg

    def __repr__(self):
        if self.id < 0:
            return "# deleted"

        return f"OBJECT {self.id} {self.lon} {self.lat} {self.hdg}"

class ObjectDef():
    is_jetway = False

    def __init__(self, id, name):
        self.id = id
        self.name = name

    def __repr__(self):
        if self.id < 0:
            return f"# deleted OBJECT_DEF {self.name}"

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

    def remove_jetways(self):
        if self.n_jw == 0:
            return

        new_id = 0
        for o in self.object_defs:
            if o.is_jetway:
                o.id = -1   # delete
            else:
                o.id = new_id
                new_id += 1

        # renumber in object_refs, deleted object propagates
        for o in self.object_refs:
            o.id = self.object_defs[o.id].id



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

n_dsf_jw = 0
for dsf in dsf_list:
    dsf.filter_jetways(sam)
    if dsf.n_jw > 0:
        n_dsf_jw += dsf.n_jw
        print(f"\nOBJECT_DEFs that are jetways in {dsf.fname}")
        for o in dsf.object_defs:
            if o.is_jetway:
                print(o)

        print(f"\nOBJECTs that are jetways in {dsf.fname}")
        for o in dsf.object_refs:
            if o.is_jetway:
                print(o)

        dsf.write()

n_sam_jw = len(sam.jetways)
if n_dsf_jw != n_sam_jw:
    log.error(f"# of jetways mismatch: dsf: {n_dsf_jw}, sam: {n_sam_jw}")
    sys.exit(2)

for dsf in dsf_list:
    dsf.remove_jetways()
    dsf.write()

apt_lines = open("Earth nav data.pre_s2n/apt.dat", "r").readlines()
with open("Earth nav data/apt.dat", "w") as f:
    for l in apt_lines:
        if l.find("99") == 0:
            for jw in sam.jetways:
                f.write(f"{jw.apt_1500()}\n")
        f.write(l)
