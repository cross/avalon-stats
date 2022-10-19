#
#

TMPZIP=tmp.zip

kawpowstats: kawpowstats.py MinerAPI.py
	rm -f __main__.py
	ln $< __main__.py
	zip -ru ${TMPZIP} __main__.py $^
	echo '#!/usr/bin/env python3' | cat - ${TMPZIP} > $@
	chmod +x $@
	rm -f ${TMPZIP} __main__.py

clean:
	rm -f ${TMPZIP} __main__.py
