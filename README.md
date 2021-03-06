Convert a modular repo. into a "compatible" repo. (works without module tools)
==============================================================================

tl;dr Run ./do.sh and it'll download from the repos. specified in reposync.conf
and generate compat. repos. named fedora-compat-\*.

The longer explanation is that the we download the modular repo. and then go
through each module within it and:
1. Extract the rpm file data.
2. Rebuild the rpm within the namespace of the module/stream it's from,
   Meaning all the requires are namespaced; including the package names
   themselves. All of the requires are then filtered to only apply within the
   module; so the rpm requires data won't pull in a packge not contained within
   the module.
3. Change the module data to reflect the new rpm names.

We also obey the blacklist-n-mods.conf and blacklist-n-rpms.conf files for
names of modules and rpms that we don't want to convert.

Also m2c.py has a bunch of commands for looking at module repodata, and altering
it in specific ways (extracting modules, renaming, merging, or just listing).
