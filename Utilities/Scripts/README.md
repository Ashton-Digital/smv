# Utilities/Scripts

This directory contains scripts for generating images and animations of FDS cases.  It also contains utility scripts used by other scripts in this repo, scripts for setting up the graphics environment for the image generating scripts and for identifying Git and compiler versions when building smoke iew. 

## Ashton Smokeview (af-smv)

`af-smv` is Ashton Fire's own build of Smokeview, installed by the Ashton
installer alongside the standard `smokeview` command. It behaves exactly like
upstream Smokeview but adds the result-review shortcuts below, plus the
`smv-cap` capture utility documented in the next section.

```shell
af-smv /path/to/case.smv
```

For a quick on-screen summary of these shortcuts and the `smv-cap` options,
run `smvhelp` (installed alongside `af-smv`/`smv-cap`; source at
`Utilities/Scripts/smv_help.sh`).

### Result-review shortcuts

Used while `af-smv` is open, in addition to all the normal Smokeview
shortcuts:

| Shortcut | Action |
| --- | --- |
| `Ctrl+I` | Cycle through the visibility slices (try `Ctrl+L` instead if this does not respond) |
| `Ctrl+T` | Cycle through the temperature slices |
| `Ctrl+V` | Cycle through the velocity slices |
| `Ctrl+P` | Cycle through the pressure slices |
| `Ctrl+U` | Unload all loaded data and return to the view from before these shortcuts were used |
| `Ctrl+X` | Cycle the X-minimum, X-maximum, and exterior views |
| `Ctrl+Y` | Cycle the Y-minimum, Y-maximum, and exterior views |
| `Ctrl+Z` | Cycle the Z-minimum, Z-maximum, and exterior views |

Hold Shift with any of the above (except `Ctrl+X`/`Ctrl+Y`/`Ctrl+Z`) to cycle
backwards instead of forwards.

Each shortcut automatically loads the relevant slice, sets the correct
colourbar and scale, cuts away the model at the slice position, switches to
the matching view, and zooms to fit. `Ctrl+U` restores the camera view and
cutaway exactly as they were before the shortcuts were first used.

If a shortcut finds no matching slices for the current case (for example, a
case with no visibility output), a message explaining this appears at the top
of the Smokeview window instead of the view changing.

### Right-click integration

Right-clicking a `.smv` file and choosing **Open With** gives two options:

- **Ashton Smokeview** — opens the case interactively, the same as
  double-clicking it or running `af-smv` from the command line.
- **Capture result slices** — runs `smv-cap` (see below) without opening an
  interactive window.

## Capture result slices window

The Windows MSI installs **Capture result slices** in the Start menu. Open it
to choose one `.smv` file or a folder of cases (with **Include subfolders** on
by default), select
visibility, temperature, velocity and pressure slices, enter one or more
simulation times separated by commas, and optionally choose an output folder.
Right-clicking an `.smv` file and choosing **Capture result slices** opens the
same window with that case preselected.
The window opens in dark mode with rounded buttons, a resizable capture log,
and a light-mode button. Its **Help** button summarizes the capture workflow;
the Windows MSI also installs **Ashton Smokeview Help** in the Start menu for
Smokeview shortcuts and capture instructions. On Linux, run `smvhelp` for the
same workflow summary. Under **Advanced: slice positions**, enable the position
filter and scan the input. Available positions appear as checked boxes; uncheck
any you do not want. For a folder, **Previous** and **Next** show each `.smv`
case and its own positions. A case with no positions checked is skipped. Leave
the filter off to capture every plane. Use **Add position manually** for a
position missing from the scan; the added position belongs to the case shown.

On Linux, the installer adds the **Capture result slices** application to the
desktop menu and the `smv-cap-ui` command. Both installers bundle the PySide6
window and its Python runtime. The capture engine on Linux still needs system
Python 3.10 or newer. The Windows MSI also includes a private ImageMagick copy.
If ImageMagick is unavailable on Linux, cropping is
disabled and full-size images are saved.

To run the window directly from a source checkout, install the Qt Widgets
binding with `python3 -m pip install PySide6-Essentials`, then run
`python3 Utilities/Scripts/capture_slices_ui.pyw` from the repository root.

By default, images go into `CASE_slice_captures` beside each `.smv` file. If
several times are entered, each time gets its own subfolder. With a chosen
output folder, the window creates a separate case folder there and preserves
the source subfolder layout for recursive batches.

## capture_result_slices.py

This script opens a Smokeview case and captures every slice configured for the
result-review shortcuts at 150 s (or the nearest available frame).  Each PNG
uses the fitted axis view at the default zoom and clips blockages at the slice
coordinate from the domain-maximum side.  Size-preserving projection is enabled
to remove perspective, and outline viewing is disabled.  The full render
includes the on-screen result label and clipping position.  By default
Smokeview uses a borderless fullscreen window, renders at the
dimensions of the user's current display, then crops each PNG to the model
with a 20-pixel white border.  All captures for the same X, Y or Z axis use a
common crop size; the colourbar, labels and time bar are removed.  Final names
are human readable, for example
`case Temperature X Slice 001 at 27.700m Clip Max.png`.

From a source checkout, run:

```shell
python3 Utilities/Scripts/capture_result_slices.py /path/to/case.smv
```

Images are written to `path/to/case_slice_captures`.  Use `-o DIR` to choose a
different directory, `--overwrite` to replace existing images,
`--size WIDTHxHEIGHT` to use a windowed capture at an explicit resolution, or
`--smokeview EXE` to select a Smokeview executable.  Use `--time SECONDS` to
override the default capture time, `--crop-padding PIXELS` to change the white
border, or `--no-crop` to retain the full render. Use `--quantities visibility
temperature` (or any subset of the four names) to render only selected result
types. The desktop window uses this option so unchecked types are skipped by
Smokeview. Cropping uses ImageMagick; the startup dependency check stops before
rendering if ImageMagick is missing unless `--no-crop` is used.
Use `--planes Y=3,Y=5` to render only those slice planes across the selected
result types. The match is by axis and position in metres; the default renders
all planes. If an individual model cannot be identified confidently, that PNG
is retained uncropped with a warning. Use `--prefix
NAME` to override the output filename prefix (default: the case name), and
`--keep-script` to retain the generated `.ssf` script file in the output
directory for troubleshooting.  When no executable is specified, the script
first looks for a compatible Smokeview beside itself, then checks this
repository's build, the `SMV` environment variable, and `PATH`; older
Smokeview releases do not contain the required `RENDERRESULTS` command.  Run
`capture_result_slices.py --help` for all options.

Installed via the Ashton installer, the equivalent command is `smv-cap`
instead of `python3 .../capture_result_slices.py`, and all the same options
apply, for example:

```shell
smv-cap /path/to/case.smv --overwrite --no-crop
```

The Ashton installers include the script with its matching custom Smokeview
build and resources:

```text
ashton-smokeview-v6.11.2-af1-linux-x64/
|-- capture_result_slices.py
|-- capture_slices_ui
|-- capture_slices_ui.pyw
|-- capture_ui_core.py
|-- smokeview
|-- smokeview.ini
|-- objects.svo
|-- colorbars/
`-- textures/
```

The launcher recognises `smokeview`, `smokeview_linux`, or `smokeview.exe`
beside itself. On Linux, install Python 3.10 or newer and ImageMagick to run
the packaged script without cloning the repository. Use `--no-crop` when
ImageMagick is intentionally unavailable. On Windows, the MSI also includes
`capture_result_slices.exe` and the portable ImageMagick files.

The Ashton installers provide operating-system integrations for the matched
capture utility. On Windows, right-click an `.smv` file and select **Capture
result slices** to open the window described above. The Windows MSI also
installs `smvhelp.txt` beside `smokeview.exe` for the result-review shortcuts
and capture options.
The equivalent PowerShell command is:

```powershell
$install = "$env:ProgramFiles\Ashton Digital\Smokeview"
& "$install\capture_result_slices.cmd" "C:\path\to\case.smv"
```

On Linux, see the right-click integration described above under "Ashton
Smokeview (af-smv)".

Normal `.smv` opening and automated capture are separate actions. Double-click
an `.smv` file to open it interactively in Ashton Smokeview. The capture action
passes the selected `.smv` path to the Python utility, which creates a temporary
Smokeview script, starts a separate automated Smokeview process, renders the
configured slices, then crops and renames the PNG files. An existing interactive
Smokeview window can remain open while capture runs. The `.smv` file and its
associated slice and data files are read from their existing locations and are
not copied into the installation.

## slice2html.sh

This script is used to generate an HTML page from an smv file. To use it, add an alias to your startup file, typically .bashrc (change the ... in the first part of the path to match your repo location):

```alias slice2html.sh=".../smv/Utilities/Scripts/slice2html.sh"```

Then type `slice2html casename` in a command shell.

## slice2mp4.sh

This script is used to generate an MP4 animation file from a slice file.  It is run on a Linux system with a queing system. To use:

1.  add the alias

```alias slice2mp4=".../smv/Utilities/Scripts/slice2mp4.sh"```

to your startup file, typically .bashrc .  Change the "..." in the first part to match your repo location.

2.  Either use smokeview you built at smv/Build/smokeview/intel_linux or use slice2mp4 with the -i option to use the smokeview installed on  your system.

3.  cd to a directory containing your case and type `slice2mp4 casename` .  You will see a list of slice files for this case such as
```
index   quantity                      dir       position
    1   U-VELOCITY                      3     255.249954
    2   V-VELOCITY                      3     255.249954
    3   VELOCITY                        3     255.249954
    4   W-VELOCITY                      3     255.249954
    5   BURNING RATE(terrain)           3           0.01
    6   LEVEL SET VALUE(terrain)        3            1.0
    7   U-VELOCITY(terrain)             3           25.0
    8   V-VELOCITY(terrain)             3           25.0
    9   VELOCITY(terrain)               3           25.0
   ```

After selecting a slice, index 9 in this example, you will see a menu for selecting various options such as scene viewpoints,  
how images are generated (number of processes, what queue to use) and an option to generate the animation.
`slice2mp4` creates a bash script and a smokeview script used by to generate the mp4 animation.

```
          slice: TEMPERATURE/Y=1.6
         bounds: default
      colour bar: show
       time bar: show
      font size: small
      viewpoint: VIEWYMIN

        PNG dir: .
        mp4 dir: /var/www/html/gforney
      smokeview: /home/gforney/FireModels_fork/smv/Build/smokeview/intel_linux/smokeview_linux
      processes: 32, node sharing on
          queue: batch
          email: gforney@gmail.com

s - select slice
b - set bounds
C - hide colour bar
T - hide time bar
F - toggle font size
v - set viewpoint

r - set PNG dir
a - set mp4 dir
m - set email address

p - set number of processes
S - toggle node sharing
q - set queue

1 - create MP4 animation
x - exit
```

Select the queue, number of processes and an email address to send the animation.  Then to generate an animation, select option 2.

## qsmv.sh

This script is used to run smokeview on a Linux cluster with a PBS or Slurm queuing system in order to generate images for creating an animation. qsmv.sh speeds up the rendering prrocess by running multiple instances of smokeview. Each instance renders a subset of the simulation time frames. By running multiple instances, the total time required to render simulation image frames is reduced.

To get started, add the following alias to your startup file, typically .bashrc 
(change the ... in the first part of the path to match where your repo is located):

```alias qsmv.sh=".../smv/Utilities/Scripts/qsmv.sh"```

To use qsmv.sh type:

```qsmv.sh casename```

(the .smv file extension is not required). This runs smokeview on the case `casename.smv` using the smokeview script `casename.ssf` . To run with a different script say `casename2.ssf` type:
```qsmv.sh -c casename2.ssf casename```

Typically, a smokeview script contains keywords such as RENDER or RENDERALL for generating images.  The keyword RENDER generates one image at one point in time.  The keyword RENDERALL generates images for all time steps in the simulation.  When RENDERALL is used, multiple instances of smokeview may be run by using -p n where n is the number of instances of smokeview where each instance generates a subset of the total images. For example if casename.smv has 1000 time steps, the command

```qsmv.sh -p 5 casename```

will run 5 instances of smokeview with each instance generating 200 images.

qsmv.sh uses either a smokeview that was built in the repo containing qsmv.sh or a smokeview found in your path.  To build smokeview perform the following steps:

1. cd smv/Build/LIBS/intel_linux
2. type: 
 ./make_LIBS.sh
3. cd smv/Build/smokeview/intel_linux 
4. type:
 ./make_smokeview.sh
 
More details on building smokeview may be found [here.](https://github.com/firemodels/smv/tree/master/Build/README.md)  To use the installed smokeview, use the `-i` option.

Details on using qsmv.sh are found below.

```
Usage: qsmv.sh [-e smv_command] [-q queue] casename

runs smokeview on the case casename.smv using the script casename.ssf

options:
 -e exe - full path of smokeview used to run case
    [default: /home/gforney/FireModels_fork/smv/Build/smokeview/intel_linux/smokeview_intel_linux]
 -h   - show commonly used options
 -H   - show all options
 -P n - run n instances of smokeview each instance rendering 1/n'th of the total images
        only use this option if you have a RENDERALL keyword in your .ssf smokeview script
 -q q - name of queue. [default: batch]
 -v   - output generated script (do not run)
Other options:
 -b     - bin directory
 -c     - smokeview script file [default: casename.ssf]
 -C com - execute the command com
 -d dir - specify directory where the case is found [default: .]
 -e exe - execute the program exe
 -i     - use installed smokeview
 -j p   - job prefix
 -N n   - reserve n cores [default: 8]
 -r     - redirect output
 -s     - first frame rendered [default: 1]
 -S     - interval between frames [default: 1]
 -T     - share nodes
```
