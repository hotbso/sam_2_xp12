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

VERSION = "1.0"

DEBUG_PARSER = False # true should reproduce the input dsf_txt verbatim
verbose = 0

import platform, sys, os, os.path, math, shlex, subprocess, shutil, re
import xml.etree.ElementTree
import logging

log = logging.getLogger("sam_2_xp12")

jw_type = None
jw_resource = ['Jetway_1_solid.fac', 'Jetway_1_glass.fac', 'Jetway_2_solid.fac', 'Jetway_2_glass.fac' ]
jw_match_radius = 0.5
jw_rotunda_length = 1.0
remove_sam_lib_objects = False

deg_2_m = 60 * 1982.0   # ° lat to m

def normalize_hdg(hdg):
    hdg = math.fmod(hdg, 360.0)
    if hdg < 0:
        hdg += 360.0
    return hdg

# position + dist@hdg, fortunately the earth is flat
def pos_plus_vec(lat, lon, dist, hdg):
    cos_lat = math.cos(math.radians(lat))
    return lat + dist / deg_2_m * math.cos(math.radians(hdg)), \
           lon + dist / (deg_2_m * cos_lat) * math.sin(math.radians(hdg))

class ObjPos():
    lat = None
    lon = None
    hdg = None

    def distance(self, obj_pos): # -> m
        if self.lat is None or obj_pos.lat is None: # it's a filter
            return 1.0E10

        dlat_m = deg_2_m * (self.lat - obj_pos.lat)
        dlon_m = deg_2_m * (self.lon - obj_pos.lon) * math.cos(math.radians(self.lat))
        return math.sqrt(dlat_m**2 + dlon_m**2)

class SAM_jw(ObjPos):
    obj_ref = None  # gets assigned if jw is matched by an object

    def __init__(self, attrib):
        #print(attrib)
        self.name = attrib['name']
        self.lat = float(attrib['latitude'])
        self.lon = float(attrib['longitude'])
        self.hdg = float(attrib['heading'])
        self.height = float(attrib['height'])
        self.length = float(attrib['cabinPos'])
        self.max_extend = float(attrib['maxExtent'])

        initialRot1 = attrib['initialRot1']
        if initialRot1 == "0":      # 0 = undefined?
            self.jw_hdg = self.hdg
        else:
            self.jw_hdg = float(initialRot1)

        self.jw_hdg = self.hdg + float(initialRot1)

        self.cab_hdg = float(attrib['initialRot2'])

        total_length = self.length + self.max_extend
        self.lcode = -1
        if self.length >= 11 and self.length <= 23:
            self.lcode = 0
        if self.length >= 14 and self.length <= 29:
            self.lcode = 1
        if self.length >= 17 and self.length <= 38:
            self.lcode = 2
        if self.length >= 20 and self.length <= 47:
            self.lcode = 3

        if self.lcode < 0:
            log.warning(f"{self}")
            log.warning(f"can't find XP12 tunnel for {self.name}, skipping")
            return

    def __repr__(self):
        return f"sam_jw '{self.name}' {self.lat} {self.lon}, length {self.length}m, extension {self.max_extend}m, " +\
               f"jw hdg: {self.jw_hdg}°, cab hdg {self.cab_hdg}°"

    def apt_1500(self):
        jw_hdg = normalize_hdg(self.jw_hdg)
        cab_hdg = normalize_hdg(self.jw_hdg + self.cab_hdg)

        return f"# '{self.name}'\n1500 {self.lat:0.8f} {self.lon:0.8f} {jw_hdg:0.1f} " + \
               f"{jw_type} {self.lcode} {jw_hdg:0.1f} {self.length:0.1f} {cab_hdg:0.1f}"

class SAM_dock(ObjPos):
    def __init__(self, attrib):
        self.lat = float(attrib['latitude'])
        self.lon = float(attrib['longitude'])
        self.hdg = normalize_hdg(90 + float(attrib['heading']))

    def __repr__(self):
        return f"sam_dock {self.lat} {self.lon} {self.hdg}°"

class SAM():
    def __init__(self):
        self.jetways = []
        self.docks = []

        root = xml.etree.ElementTree.parse("sam.xml").getroot()
        for e in root.find('jetways').findall('jetway'):
            jw = SAM_jw(e.attrib)
            if 3.5 <= jw.height and jw.height <= 6.0 and jw.lcode >= 0: # only in the range of XP12
                self.jetways.append(jw)

        for e in root.find('docks').findall('dock'):
            self.docks.append(SAM_dock(e.attrib))

    def match_docks(self, obj_ref):
        for dock in self.docks:
            if dock.distance(obj_ref) < 1:
                return True

        return False

class ObjectRef(ObjPos):
    sam_jw = None  # backlink to sam definition

    split_3 = re.compile("([^ ]+) +([^ ]+) +(.*)")          # 2 words + remainder

    def __init__(self, obj, line):
        self.obj = obj
        m = self.split_3.match(line)
        self.type = m.group(1)
        id = int(m.group(2))
        assert id == obj.id

        # we try to keep params verbatim for easier diff of text files
        self.params = m.group(3)

        words = self.params.split()
        self.lon = float(words[0])
        self.lat = float(words[1])

        # OBJECT is lon, lat, hdg
        if self.type == "OBJECT":
            self.hdg = float(words[2])
            return

        # OBJECT_MSL or _AGL is lon, lat, height, hdg
        height = float(words[2])
        # height may be < 0 on imported records but that bombs on text2dsf
        if height < 0:
            words[2] = "0.0"
            self.params = " ".join(words)

        self.hdg = float(words[3])

    def __repr__(self):
        id = self.obj.id
        if id < 0:
            return f"# deleted {self.type} {id} {self.params}"

        return f"{self.type} {id} {self.params}"

class ObjectDef():
    sam_checked = False
    sam_jw = False
    is_jetway = False
    is_dock = False

    def __init__(self, id, name):
        self.id = id
        self.name = name

    def is_sam_jw(self):
        """ Check whether .OBJ file contains a sam dataref"""
        if not self.sam_checked:
            self.sam_checked = True
            if os.path.isfile(self.name):
                for l in open(self.name, "r").readlines():
                    if l.find("sam/jetway/rotate1") >= 0:
                        self.sam_jw = True
                        log.info(f"{self} is a SAM controlled jetway obj")
                        break

        return self.sam_jw

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

        dsf_txt = self.dsf_base + ".txt_pre"

        self.run_cmd(f'"{dsf_tool}" -dsf2text "{self.fname}" "{dsf_txt}"')

        self.dsf_lines = [] # anything with __repr__ method

        self.jw_facade_id = 0
        obj_id = 0
        self.object_defs = []
        self.object_refs = []

        for l in open(dsf_txt, "r").readlines():
            l = l.rstrip()

            if l.find("OBJECT_DEF") == 0:
                l = ObjectDef(obj_id, l[11:])   # object def can contain blanks
                self.object_defs.append(l)
                obj_id += 1
            elif l.find("OBJECT") == 0:         # OBJECT[_AGL|_MSL]
                id = int(l.split()[1])
                l = ObjectRef(self.object_defs[id], l)
                self.object_refs.append(l)
            elif l.find("POLYGON_DEF") == 0:
                self.jw_facade_id += 1          # just count jw_facade_id

            self.dsf_lines.append(l)

    def __repr__(self):
        return f"{self.fname}"

    def run_cmd(self, cmd):
        # "shell = True" is not needed on Windows, bombs on Lx
        out = subprocess.run(shlex.split(cmd), capture_output = True)
        if out.returncode != 0:
            log.error(f"Can't run {cmd}: {out}")
            sys.exit(2)

    def filter_sam(self, sam):
        for jw in sam.jetways:
            candidates = []

            # find possible candidates by proximity
            for o_r in self.object_refs:
                if jw.distance(o_r) < jw_match_radius:
                    candidates.append(o_r)

            # check if one of these is a SAM jetway
            # then mark this alone
            have_sam_jw = False
            for o_r in candidates:
                obj = o_r.obj
                if obj.is_sam_jw():
                    have_sam_jw = True
                    o_r.sam_jw = jw
                    jw.obj_ref = o_r
                    obj.is_jetway = True
                    self.n_jw += 1
                    break

            # no SAM controlled jetway obj found, mark all
            if not have_sam_jw:
                for o_r in candidates:
                    o_r.sam_jw = jw
                    jw.obj_ref = o_r
                    obj.is_jetway = True
                    self.n_jw += 1

        # finding docks is simpler
        for o_r in self.object_refs:
            if sam.match_docks(o_r):
                o_r.is_dock = True
                o_r.obj.is_dock = True
                self.n_docks += 1

    def write(self):
        dsf_txt = self.dsf_base + ".txt"
        with open(dsf_txt, "w") as f:
            for l in self.dsf_lines:
                if l.__class__ is ObjectDef:
                    f.write(f"# {l.id}\n")
                f.write(f"{l}\n")

        self.run_cmd(f'"{dsf_tool}" -text2dsf "{dsf_txt}" "{self.dsf_base}.dsf"')

    def remove_sam(self):
        changed = False

        new_id = 0
        for o in self.object_defs:
            if ((o.is_jetway or o.is_dock) or
                (remove_sam_lib_objects and
                    (o.name.find("SAM_Library") >= 0 or o.name.find("SAM3_Library") >= 0))):
                o.id = -1   # delete
                changed = True
            else:
                o.id = new_id
                new_id += 1

        if not changed:
            return False

        return True # changed

    def add_rotundas(self, sam):
        self.dsf_lines.append(f"POLYGON_DEF lib/airport/Ramp_Equipment/Jetways/{jw_resource[jw_type]}")

        for jw in sam.jetways:
            if jw.obj_ref is None:
                log.warning(f"Unmatched sam jetway: {jw}")
                continue    # sam definition is not matched by an object

            if jw.obj_ref:
                lat2 = jw.obj_ref.lat
                lon2 = jw.obj_ref.lon
                hdg = jw.obj_ref.hdg
            else:
                lat2 = jw.lat
                lon2 = jw.lon
                hdg = jw.hdg

            lat1, lon1 = pos_plus_vec(lat2, lon2, -jw_rotunda_length, hdg)

            self.dsf_lines.append(f"# '{jw.name}'\nBEGIN_POLYGON {self.jw_facade_id} 5 3")
            self.dsf_lines.append("BEGIN_WINDING");
            self.dsf_lines.append(f"POLYGON_POINT {lon1:0.7f} {lat1:0.7f} 0.0")
            self.dsf_lines.append(f"POLYGON_POINT {lon2:0.7f} {lat2:0.7f} 0.0")
            self.dsf_lines.append("END_WINDING")
            self.dsf_lines.append("END_POLYGON")


###########
## main
###########
logging.basicConfig(level=logging.INFO,
                    handlers=[logging.FileHandler(filename = "sam_2_xp12.log", mode='w'),
                              logging.StreamHandler()])

log.info(f"Version: {VERSION}")
log.info(f"args: {sys.argv}")

def usage():
    log.error( \
        """sam_2_xp12 -jw_type 0..3 [-jw_match_radius d] [-jw_rotunda_length d] [-remove_sam_lib_objects] [-verbose]
            -jw_type 0..3
                0: light-solid
                1: light-glass
                2: dark-solid
                3: dark-glass

            -jw_match_radius d
                distance in meters to match sam coordinates with scenery objects
                default: 0.5

            -jw_rotunda_length d
                length of the rotunda segment
                default: 1.0

            -remove_sam_lib_objects
                remove all references to the SAM*_Library
         """)
    sys.exit(2)

mode = None

i = 1
while i < len(sys.argv):
    if sys.argv[i] == "-jw_type":
        i = i + 1
        if i >= len(sys.argv):
            usage()
        jw_type = int(sys.argv[i])
    elif sys.argv[i] == "-jw_match_radius":
        i = i + 1
        if i >= len(sys.argv):
            usage()
        jw_match_radius = float(sys.argv[i])
    elif sys.argv[i] == "-jw_rotunda_length":
        i = i + 1
        if i >= len(sys.argv):
            usage()
        jw_rotunda_length = float(sys.argv[i])
    elif sys.argv[i] == "-verbose":
        verbose = 1
    elif sys.argv[i] == "-remove_sam_lib_objects":
        remove_sam_lib_objects = True
    else:
        usage();

    i = i + 1

if jw_type is None:
    usage()

dsf_tool = os.path.join(os.path.dirname(sys.argv[0]), 'DSFTool')
if platform.system() == 'Windows':
    dsf_tool += ".exe"

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
n_sam_jw = len(sam.jetways)
n_sam_docks = len(sam.docks)
log.info(f"Found {n_sam_jw} jetways and {n_sam_docks} docks in sam.xml")

if verbose > 1:
    log.info("SAM jetways and dock")
    for jw in sam.jetways:
        log.info(f" {jw}")

    for d in sam.docks:
        log.info(f" {d}")

dsf_list = []
for dir, dirs, files in os.walk(src_dir):
    for f in files:
        _, ext = os.path.splitext(f)
        if ext != '.dsf':
            continue

        full_name = os.path.join(dir, f)
        log.info(f"Processing {full_name}")
        dsf_list.append(Dsf(full_name))


n_dsf_jw = 0
n_dsf_docks = 0
for dsf in dsf_list:
    dsf.filter_sam(sam)
    if dsf.n_jw > 0:
        n_dsf_jw += dsf.n_jw
        if verbose > 0:
            log.info("")
            log.info(f"OBJECT_DEFs that belong to jetways in {dsf.fname}")
            for o in dsf.object_defs:
                if o.is_jetway:
                    log.info(f"{o.id:3d}: {o}")

            log.info("")
            log.info(f"OBJECT refs that belong to jetways in {dsf.fname}")
            for o_r in dsf.object_refs:
                if o_r.obj.is_jetway:
                    log.info(f" {o_r.sam_jw.name:8} {o_r}")

    if dsf.n_docks > 0:
        n_dsf_docks += dsf.n_docks
        if verbose > 0:
            log.info("")
            log.info(f"OBJECT_DEFs that are docks in {dsf.fname}")
            for o in dsf.object_defs:
                if o.is_dock:
                    log.info(f" {o}")

            log.info("")
            log.info(f"OBJECT refs that are docks in {dsf.fname}")
            for o_r in dsf.object_refs:
                if o_r.obj.is_dock:
                    log.info(f" {o_r}")

log.info(f"Identified {n_dsf_jw} jetways and {n_dsf_docks} docks in .dsf files")

log.info("Removing sam jetways and docks from dsf and creating rotundas")
for dsf in dsf_list:
    if DEBUG_PARSER:
        dsf.write()
    else:
        if dsf.remove_sam():
            dsf.add_rotundas(sam)
            dsf.write()

if DEBUG_PARSER:
    sys.exit(0)

log.info("Creating XP12 jetways in apt.dat")
apt_lines = open("Earth nav data.pre_s2n/apt.dat", "r").readlines()
with open("Earth nav data/apt.dat", "w") as f:
    for l in apt_lines:
        if l.find("99") == 0:
            for jw in sam.jetways:
                if not jw.obj_ref is None and jw.lcode >= 0:
                    f.write(f"{jw.apt_1500()}\n")
        f.write(l)

sam_lib_refs = []
for dsf in dsf_list:
    for o in dsf.object_defs:
        if (o.id >= 0 and
            (o.name.find("SAM_Library") >= 0 or o.name.find("SAM3_Library") >= 0)):
            sam_lib_refs.append(o)

if len (sam_lib_refs) > 0:
    log.warning("There are still refereces to SAM_Library")
    for o in sam_lib_refs:
        log.info(f" {o}")
else:
    log.info("No more references to SAM*_Library found!")

open("Earth nav data/use_autodgs", "w")
log.info('done!')
