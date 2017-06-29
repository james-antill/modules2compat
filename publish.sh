#! /bin/sh -e

if [ "x$1" = "x" ]; then
    echo "Format: $0 <dir>"
    exit 1
fi

if [ ! -d "$1" ]; then
    echo "Format: $0 <dir>"
    exit 1
fi

for i in '' '-nodejs' '-rawhide'; do
 cp -a fedora-compat-modular$i $1
 mv $1/fedora-modular$i $1/fedora-modular$i.old
 mv $1/fedora-compat-modular$i $1/fedora-modular$i
 rm -rf $1/fedora-modular$i.old
done

