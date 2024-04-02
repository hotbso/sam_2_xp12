Installation:
-------------

Just extract the zip file to a folder of your liking. I recommend outside of the XP12 hierarchy.
Download xptools from https://developer.x-plane.com/tools/xptools/ and place DFSTool[.exe] into
the same folder.

How it works:
-------------
Open a command shell in the folder of a scenery with SAM jetways. If the scenery comprises of several folders
be sure you enter the one that contains file "apt.dat" in "Earth nav data".

E.g.
"E:\X-Plane-12-test\Custom Scenery\Captain7 - 29Palms - EDDN Nuremberg 2"

From there invoke the script or exe:
"your_install_folder\sam_2_xp12.py  -jw_type 2 -jw_match_radius 0.8"

The script first copies "Earth nav data" to "Earth nav data.pre_s2n" *ONCE* and then always
works by reading from "Earth nav data.pre_s2n" and writing to "Earth nav data".

Therefore you can run the script multiple times testing parameters or if you are unhappy with the
conversion just delete "Earth nav data" and rename back "Earth nav data.pre_s2n" to "Earth nav data".

The script directly manipulates the .dsf and apt.dat files. So if you imported these into WED you
have to do it again.
Nevertheless it's always a good idea to do an extra backup or have your distribution media at hand.

See screenshots.

