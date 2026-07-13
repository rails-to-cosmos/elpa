
Buffer-based interactive editor for display configuration.
Currently shells out to xrandr/autorandr (X11); Wayland support is on
the roadmap.  No native code; pure Elisp.

Usage:
  M-x darr            open the layout buffer (alias for darr-show)

Inside the *Displays* buffer:
  n / p     next / previous display
  h j k l   move selected display left/down/up/right relative to neighbor
  r / R     cycle resolution forward / backward
  F         cycle refresh rate
  o         cycle rotation (normal / left / inverted / right)
  P         mark as primary
  d         disable display
  e         enable display
  T         toggle showing disconnected outputs
  C-c C-c   apply with xrandr
  C-c C-k   revert: discard unapplied changes (re-read from xrandr)
  C-c C-s   save current as autorandr profile
  C-c C-l   load autorandr profile
  C-c C-d   delete saved autorandr profile
  g         refresh from xrandr
