#! /bin/sh -e

./m2c.py fedora-modular/9980872a7c627d798989188c9328542dec58eff5b54f3f4f65dd19b251831e32-modules.yaml.gz fedora-modular/Packages fm-out-1

./m2c.py fedora-modular-rawhide/e79901f3065b864dda3a7e5bf88e7208d832fe17058890b9069d59e8de9ef9e1-modules.yaml.gz fedora-modular-rawhide/Packages/ fm-out-2

./m2c.py fedora-modular-nodejs/55336e14702f1cc6008578153dc557dc60ddf776290b1a9644f27d586e82b896-modules.yaml.gz fedora-modular-nodejs fm-out-3
