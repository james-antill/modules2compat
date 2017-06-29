#! /bin/sh -e

reposync=reposync

# DNF reposync isn't compatible, as usual.
if false && [ -x /usr/bin/dnf ]; then
  reposync="dnf reposync"
fi

rm -f */*-modules.yaml.gz
$reposync --config=reposync.conf --download-metadata

for i in modular modular-rawhide modular-nodejs; do

 mkdir fedora-compat-$i || true
 if [ -d fedora-$i/Packages ]; then
    ./m2c.py fedora-$i/*-modules.yaml.gz fedora-$i/Packages fedora-compat-$i
 else
    ./m2c.py fedora-$i/*-modules.yaml.gz fedora-$i fedora-compat-$i
 fi

done

./build-repos.sh fedora-compat-*

./publish.sh www
