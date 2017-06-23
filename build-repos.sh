#! /bin/sh -e

for i in $@; do
    createrepo $i
    mv $i/modmd $i/modules.yaml || true
    modifyrepo $i/modules.yaml $i/repodata/
done
