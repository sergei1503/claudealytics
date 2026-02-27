# VHS tape for claudealytics publish demo
# Run: vhs docs/demo.tape

Output docs/demo.gif

Set FontSize 16
Set Width 900
Set Height 500
Set Theme "Catppuccin Mocha"
Set Padding 20

Type "uvx claudealytics publish"
Sleep 500ms
Enter

Sleep 8s

# Wait for browser to open
Sleep 3s
