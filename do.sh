#! /bin/sh -e

reposync=reposync

# DNF reposync isn't compatible, as usual.
if false && [ -x /usr/bin/dnf ]; then
  reposync="dnf reposync"
fi

rm -f */*-modules.yaml.gz
$reposync --config=reposync.conf --download-metadata

for i in modular modular-rawhide modular-nodejs; do

  ./m2c.py convert fedora-compat-$i fedora-$i/*-modules.yaml.gz

done

./build-repos.sh fedora-compat-*

./publish.sh www
