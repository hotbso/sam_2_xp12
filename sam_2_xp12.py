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

VERSION = "1.0-b1"

verbose = 0

import platform, sys, os, os.path, math, shlex, subprocess, shutil, re
import logging

log = logging.getLogger("sam_2_native")

jw_type = None
jw_resource = ['Jetway_1_solid.fac', 'Jetway_1_glass.fac', 'Jetway_2_solid.fac', 'Jetway_2_glass.fac' ]
jw_match_radius = 0.5

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
        dlat_m = deg_2_m * (self.lat - obj_pos.lat)
        dlon_m = deg_2_m * (self.lon - obj_pos.lon) * math.cos(math.radians(self.lat))
        return math.sqrt(dlat_m**2 + dlon_m**2)

class SAM_jw(ObjPos):
    obj_ref = None  # gets assigned if jw is matched by an object

    #<jetway name="Gate 11" latitude="49.495060845089135" longitude="11.077626914186194" heading="8.2729158401489258"
    # height="4.33699989" wheelPos="9.35599995" cabinPos="17.6229992" cabinLength="2.84500003"
    # wheelDiameter="1.21200001" wheelDistance="1.79999995" sound="alarm2.ogg"
    # minRot1="-85" maxRot1="5" minRot2="-72" maxRot2="41" minRot3="-6" maxRot3="6"
    # minExtent="0" maxExtent="15.3999996" minWheels="-2" maxWheels="2"
    # initialRot1="-60.0690002" initialRot2="-37.8320007" initialRot3="-3.72300005" initialExtent="0" />
    jw_re = re.compile('.* name="([^"]+).* latitude="([^"]+)".* longitude="([^"]+)".* heading="([^"]+)"' +
                       '.* height="([^"]+)".* cabinPos="([^"]+)".* maxExtent="([^"]+)"' +
                       '.* initialRot1="([^"]+)".* initialRot2="([^"]+)".*')

    def __init__(self, line):
        m = self.jw_re.match(line)
        if m is None:
            log.error(f"Cannot parse jetway line: '{line}'")
        self.name = m.group(1)
        self.lat = float(m.group(2))
        self.lon = float(m.group(3))
        self.hdg = float(m.group(4))
        self.height = float(m.group(5))
        self.length = float(m.group(6))
        self.max_extend = float(m.group(7))

        initialRot1 = m.group(8)
        if initialRot1 == "0":      # 0 = undefined?
            self.jw_hdg = self.hdg
        else:
            self.jw_hdg = float(initialRot1)

        self.jw_hdg = self.hdg + float(initialRot1)

        self.cab_hdg = float(m.group(9))

    def __repr__(self):
        return f"sam_jw '{self.name}' {self.lat} {self.lon} {self.length}m {self.max_extend}m " +\
               f"{self.jw_hdg}° {self.cab_hdg}°"

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

        return f"# '{self.name}'\n1500 {self.lat:0.8f} {self.lon:0.8f} {jw_hdg:0.1f} " + \
               f"{jw_type} {lcode} {jw_hdg:0.1f} {self.length:0.1f} {cab_hdg:0.1f}"

class SAM_dock(ObjPos):
    #<dock id="GA 2" latitude="49.496759842417845" longitude="11.069054733293136"
    # elevation="317.60116324946284" heading="98.552436828613281"
    # dockLatitude="49.496774936124368" dockLongitude="11.068896558384955" dockHeading="98.230850219726563" />
    dock_re = re.compile('.* latitude="([^"]+)".* longitude="([^"]+)".* heading="([^"]+)"')

    def __init__(self, line):
        m = self.dock_re.match(line)
        if m is None:
            log.error(f"Cannot parse dock line: '{line}'")

        self.lat = float(m.group(1))
        self.lon = float(m.group(2))
        self.hdg = normalize_hdg(90 + float(m.group(3)))

    def __repr__(self):
        return f"sam_dock {self.lat} {self.lon} {self.hdg}°"

class SAM():
    def __init__(self):
        self.jetways = []
        self.docks = []

        for l in open("sam.xml", "r").readlines():
            if l.find("<jetway ") > 0:
                jw = SAM_jw(l)
                if 3.5 <= jw.height and jw.height <= 6.0: # only in the range of XP12
                    self.jetways.append(jw)

            elif l.find("<dock ") > 0:
                self.docks.append(SAM_dock(l))

    def match_jetways(self, obj_ref):
        for jw in self.jetways:
            if jw.distance(obj_ref) < jw_match_radius:
                obj_ref.sam_jw = jw
                jw.obj_ref = obj_ref  # save obj reference
                return True

        return False

    def match_docks(self, obj_ref):
        for dock in self.docks:
            if dock.distance(obj_ref) < 1:
                return True

        return False

class ObjectRef(ObjPos):
    is_jetway = False
    is_dock = False
    sam_jw = None  # backlink to sam object

    split_3 = re.compile("([^ ]+) +([^ ]+) +(.*)")          # 2 words + remainder
    extract_3 = re.compile("([^ ]+) +([^ ]+) +([^ ]+).*")   # 3 words

    def __init__(self, line):
        m = self.split_3.match(line)
        self.type = m.group(1)
        self.id = int(m.group(2))
        self.params = m.group(3)

        m = self.extract_3.match(self.params)
        self.lat = float(m.group(2))
        self.lon = float(m.group(1))
        self.hdg = float(m.group(3))

    def __repr__(self):
        if self.id < 0:
            return f"# deleted {self.type} {self.id} {self.params}"

        return f"{self.type} {self.id} {self.params}"

class ObjectDef():
    is_jetway = False
    is_dock = False

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

        obj_id = 0
        dsf_txt = self.dsf_base + ".txt_pre"

        self.run_cmd(f'"{dsf_tool}" -dsf2text "{self.fname}" "{dsf_txt}"')

        dsf_txt_lines = open(dsf_txt, "r").readlines()
        self.object_defs = []
        self.object_refs = []
        self.polygon_defs = []
        self.polygon_refs = []
        self.rest = []

        for l in dsf_txt_lines:
            l = l.rstrip()
            if len(l) == 0 or l[0] == "#":
                continue

            #print(l)
            if l.find("OBJECT_DEF") == 0:
                self.object_defs.append(ObjectDef(obj_id, l[11:]))   # object def can contain blanks
                obj_id += 1
                continue

            if l.find("OBJECT") == 0:
                self.object_refs.append(ObjectRef(l))
                continue

            if l.find("POLYGON_DEF") == 0:
                self.polygon_defs.append(l)
                continue

            if l.find("POLYGON") >= 0 or l.find("WINDING") >= 0:
                self.polygon_refs.append(l)
                continue

            self.rest.append(l)

    def __repr__(self):
        return f"{self.fname}"

    def run_cmd(self, cmd):
        # "shell = True" is not needed on Windows, bombs on Lx
        out = subprocess.run(shlex.split(cmd), capture_output = True)
        if out.returncode != 0:
            log.error(f"Can't run {cmd}: {out}")
            sys.exit(2)


    def filter_sam(self, sam):
        for o in self.object_refs:
            if sam.match_jetways(o):
                o.is_jetway = True
                self.object_defs[o.id].is_jetway = True
                self.n_jw += 1
                continue

            if sam.match_docks(o):
                o.is_dock = True
                self.object_defs[o.id].is_dock = True
                self.n_docks += 1

    def write(self):
        dsf_txt = self.dsf_base + ".txt"
        with open(dsf_txt, "w") as f:
            for section in [self.rest, self.object_defs, self.polygon_defs,
                            self.object_refs, self.polygon_refs]:
                for o in section:
                    f.write(f"{o}\n")

        self.run_cmd(f'"{dsf_tool}" -text2dsf "{dsf_txt}" "{self.dsf_base}.dsf"')

    def remove_sam(self):
        if self.n_jw == 0 and self.n_docks == 0:
            return False

        new_id = 0
        for o in self.object_defs:
            if o.is_jetway or o.is_dock:
                o.id = -1   # delete
            else:
                o.id = new_id
                new_id += 1

        # renumber in object_refs, deleted object propagate
        for o in self.object_refs:
            o.id = self.object_defs[o.id].id

        return True # changed

    def add_rotundas(self, sam):
        self.polygon_defs.append(f"POLYGON_DEF lib/airport/Ramp_Equipment/Jetways/{jw_resource[jw_type]}")
        id = len(self.polygon_defs) - 1

        rotunda_len = 1.5

        for jw in sam.jetways:
            if jw.obj_ref is None:
                log.warning(f"Unmatched sam jetway: {jw}")
                continue    # sam definition is not matched by an object

            lat = jw.lat
            lon = jw.lon
            #lat = jw.obj_ref.lat
            #lon = jw.obj_ref.lon

            lat1, lon1 = pos_plus_vec(lat, lon, rotunda_len, jw.obj_ref.hdg)

            self.polygon_refs.append(f"# '{jw.name}'\nBEGIN_POLYGON {id} 5 3")
            self.polygon_refs.append("BEGIN_WINDING");
            self.polygon_refs.append(f"POLYGON_POINT {lon:0.7f} {lat:0.7f} 0.0")
            self.polygon_refs.append(f"POLYGON_POINT {lon1:0.7f} {lat1:0.7f} 0.0")
            self.polygon_refs.append("END_WINDING")
            self.polygon_refs.append("END_POLYGON")

            # center of rotunda
            jw.lat = lat1
            jw.lon = lon1


###########
## main
###########
logging.basicConfig(level=logging.INFO,
                    handlers=[logging.FileHandler(filename = "sam_2_native.log", mode='w'),
                              logging.StreamHandler()])

log.info(f"Version: {VERSION}")
log.info(f"args: {sys.argv}")

def usage():
    log.error( \
        """sam_2_native -jw_type 0..3 [-jw_match_radius d] [-verbose]
            -jw_type 0..3
                0: light-solid
                1: light-glass
                2: dark-solid
                3: dark-glass

            -jw_match_radius d:
                distance in meters to match sam coordnates with secenery objects
                default: 0.5

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
    elif sys.argv[i] == "-verbose":
        verbose = 1

    i = i + 1

if jw_type is None:
    usage()

dsf_tool = os.path.join(os.path.dirname(sys.argv[0]), 'dsftool')
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
            log.info(f"OBJECTs that belong to jetways in {dsf.fname}")
            for o in dsf.object_refs:
                if o.is_jetway:
                    log.info(f" {o.sam_jw.name:8} {o}")

    if dsf.n_docks > 0:
        n_dsf_docks += dsf.n_docks
        if verbose > 0:
            log.info("")
            log.info(f"OBJECT_DEFs that are docks in {dsf.fname}")
            for o in dsf.object_defs:
                if o.is_dock:
                    log.info(f" {o}")

            log.info("")
            log.info(f"OBJECTs that are docks in {dsf.fname}")
            for o in dsf.object_refs:
                if o.is_dock:
                    log.info(f" {o}")

log.info(f"Identified {n_dsf_jw} jetways and {n_dsf_docks} docks in .dsf files")

log.info("Removing sam jetways and docks from dsf and creating rotundas")
for dsf in dsf_list:
    if dsf.remove_sam():
        dsf.add_rotundas(sam)
        dsf.write()

log.info("Creating XP12 jetways in apt.dat")
apt_lines = open("Earth nav data.pre_s2n/apt.dat", "r").readlines()
with open("Earth nav data/apt.dat", "w") as f:
    for l in apt_lines:
        if l.find("99") == 0:
            for jw in sam.jetways:
                f.write(f"{jw.apt_1500()}\n")
        f.write(l)

sam_lib_refs = []
for dsf in dsf_list:
    for o in dsf.object_defs:
        if o.id >= 0 and o.name.find("SAM_Library") >= 0 or \
           o.name.find("SAM3_Library") >= 0:
            sam_lib_refs.append(o)

if len (sam_lib_refs) > 0:
    log.warning("There are still refereces to SAM_Library")
    for o in sam_lib_refs:
        log.info(f" {o}")
else:
    log.info("No more references to SAM*_Library found!")

open("Earth nav data/use_autodgs", "w")
log.info('done!')
