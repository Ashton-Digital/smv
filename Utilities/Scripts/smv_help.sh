#!/bin/bash
# Prints a summary of the Ashton Fire af-smv/smv-cap shortcuts and options.
# Colour is used only when stdout is an interactive terminal that supports it,
# so piping/redirecting this (e.g. `smvhelp > notes.txt`) still gives plain text.

if [ -t 1 ] && command -v tput >/dev/null 2>&1 && [ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]; then
  BOLD="$(tput bold)"
  RESET="$(tput sgr0)"
  HEAD="$(tput bold)$(tput setaf 6)"   # bold cyan section headings
  KEY="$(tput bold)$(tput setaf 3)"    # bold yellow shortcut keys
  CMD="$(tput bold)$(tput setaf 2)"    # bold green command names
  NOTE="$(tput setaf 5)"               # magenta notes
else
  BOLD=""; RESET=""; HEAD=""; KEY=""; CMD=""; NOTE=""
fi

echo "To view FDS results using Ashton Fire's custom Smokeview build:"
echo "${CMD}af-smv${RESET} <file_name>"
echo
echo "af-smv is Ashton Fire's own build of Smokeview. It behaves exactly like the standard smokeview command, but adds"
echo "several keyboard shortcuts and a companion capture tool described below. Use ${CMD}af-smv${RESET} instead of"
echo "smokeview so that these are available."
echo
echo "${HEAD}Ashton Fire result-review shortcuts${RESET} (used while af-smv is open, in addition to all the normal"
echo "Smokeview shortcuts):"
echo "${KEY}Ctrl+I${RESET} - cycle through the visibility slices (if this does not respond, try ${KEY}Ctrl+L${RESET} instead)"
echo "${KEY}Ctrl+T${RESET} - cycle through the temperature slices"
echo "${KEY}Ctrl+V${RESET} - cycle through the velocity slices"
echo "${KEY}Ctrl+P${RESET} - cycle through the pressure slices"
echo "${KEY}Ctrl+U${RESET} - unload all loaded data and return to how the view looked before these shortcuts were used"
echo "${KEY}Ctrl+X${RESET} - cycle the X-minimum, X-maximum, and exterior views"
echo "${KEY}Ctrl+Y${RESET} - cycle the Y-minimum, Y-maximum, and exterior views"
echo "${KEY}Ctrl+Z${RESET} - cycle the Z-minimum, Z-maximum, and exterior views"
echo "Hold ${BOLD}Shift${RESET} with any of the above (except Ctrl+X/Y/Z) to cycle backwards instead of forwards."
echo
echo "Each shortcut automatically loads the relevant slice, sets the correct colour bar and scale, cuts away the model"
echo "at the slice position, switches to the matching view, and zooms to fit. Pressing ${KEY}Ctrl+U${RESET} at any point"
echo "restores the camera view and cutaway exactly as they were before you started using these shortcuts."
echo
echo "${NOTE}Note:${RESET} if a shortcut does not find any matching slices for the current job (for example if a job has"
echo "no visibility output), a short message explaining this appears at the top of the Smokeview window rather than"
echo "the view changing."
echo
echo "To capture images of these slices automatically instead of stepping through them by hand:"
echo "${CMD}smv-cap${RESET} <file_name>"
echo "This opens the job in the background, saves an image of every configured visibility, temperature, velocity and"
echo "pressure slice, then closes again. Your own interactive af-smv window, if you have one open, is not affected and"
echo "can be left running. Images are saved into a new folder alongside the .smv file, named <file_name>_slice_captures."
echo
echo "${HEAD}Useful smv-cap options:${RESET}"
echo "${KEY}--overwrite${RESET} - replace images from a previous run instead of skipping them"
echo "${KEY}--no-crop${RESET} - keep the full-size image instead of cropping tightly around the model"
echo "${KEY}-o <directory>${RESET} - save images to a chosen folder instead of the default one"
echo "${KEY}--time <seconds>${RESET} - capture a different simulation time instead of the default 150 s"
echo "${KEY}--planes Y=3,Y=5${RESET} - capture only slices at the listed axis positions (metres)"
echo "${KEY}--prefix <name>${RESET} - use a different filename prefix instead of the case name"
echo "${KEY}--crop-padding <pixels>${RESET} - change the white border width around cropped images (default: 20)"
echo
echo "${HEAD}Right-click integration:${RESET}"
echo "Right-clicking a .smv file and choosing Open With gives two options:"
echo "${BOLD}Ashton Smokeview${RESET} - opens the job interactively, the same as double-clicking it or typing af-smv"
echo "from the command line."
echo "${BOLD}Capture result slices${RESET} - runs the automatic capture described above, without opening an"
echo "interactive window."
